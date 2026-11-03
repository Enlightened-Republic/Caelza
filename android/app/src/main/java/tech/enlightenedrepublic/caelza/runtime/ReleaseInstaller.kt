package tech.enlightenedrepublic.caelza.runtime

import org.apache.commons.compress.archivers.tar.TarArchiveInputStream
import org.apache.commons.compress.compressors.gzip.GzipCompressorInputStream
import org.json.JSONObject
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * One HTTP GET; a seam so the tests hand the installer a canned GitHub. `get` is for the
 * small answers (the release JSON, a checksum); `download` streams a large one to a file,
 * so a 60 MB tarball never sits in a 192 MB heap twice over.
 */
fun interface Fetch {
    fun get(url: String, accept: String): ByteArray

    fun download(url: String, accept: String, into: File) {
        into.writeBytes(get(url, accept))
    }
}

/** `HttpURLConnection` with the GitHub headers; redirects to the asset storage follow without a token. */
class HttpFetch(private val token: String? = null) : Fetch {
    override fun get(url: String, accept: String): ByteArray = open(url, accept) { it.readBytes() }

    override fun download(url: String, accept: String, into: File) {
        open(url, accept) { input -> FileOutputStream(into).use { input.copyTo(it) } }
    }

    private fun <T> open(url: String, accept: String, read: (java.io.InputStream) -> T): T {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 20_000
        conn.readTimeout = 120_000
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("Accept", accept)
        conn.setRequestProperty("User-Agent", "caelza-android runtime guard")
        if (token != null && conn.url.host == "api.github.com") conn.setRequestProperty("Authorization", "token $token")
        try {
            if (conn.responseCode !in 200..299) throw IllegalStateException("HTTP ${conn.responseCode} for $url")
            return conn.inputStream.use(read)
        } finally {
            conn.disconnect()
        }
    }
}

data class Release(val tag: String, val version: String, val name: String, val assetUrl: String, val shaUrl: String?)

data class ProbeResult(val ok: Boolean, val detail: String)

/** Does a binary hold? `--version` must match, the gateway must serve `/health`. */
fun interface Prober {
    fun probe(binary: File, expectVersion: String, configDir: File?): ProbeResult
}

data class UpdateResult(
    val version: String,
    val promoted: Boolean,
    val detail: String,
    val previous: String? = null,
    val lastGood: String? = null,
)

/**
 * The guard's pipeline (`caelza_body/runtime_guard.py`) in the app: find the
 * release's archive for this target, download it with its `.sha256`, verify,
 * unpack into a work dir, probe the binary there on a copy of the config,
 * then install, move `current` and keep `last-good` on the version that was
 * running (the first install is both). A binary that does not hold is never
 * installed and the one running stays.
 */
class ReleaseInstaller(
    private val store: RuntimeStore,
    private val fetch: Fetch = HttpFetch(),
    private val prober: Prober = ProcessProber(),
    private val target: String = TARGET,
    private val repo: String = DEFAULT_REPO,
    private val log: (String) -> Unit = {},
) {
    fun findRelease(tag: String? = null): Release {
        val normalized = tag?.trim()?.takeIf { it.isNotEmpty() }?.let { if (SEMVER.matches(it)) "v$it" else it }
        val url = if (normalized != null) "$RELEASES_API/$repo/releases/tags/$normalized" else "$RELEASES_API/$repo/releases/latest"
        return parseRelease(String(fetch.get(url, "application/vnd.github+json")), target)
    }

    /** With `archive`, a local tarball (no network; its `.sha256` beside it is honoured). */
    fun update(tag: String? = null, archive: File? = null): UpdateResult {
        val work = File(store.home, "tmp/runtime-update-${System.nanoTime()}").apply { mkdirs() }
        try {
            val version: String
            val tarball: File
            var shaText: String? = null
            if (archive != null) {
                version = versionFromName(archive.name, target) ?: archive.name.removeSuffix(".tar.gz")
                if (version == store.current && store.currentBinary != null) {
                    log("$version is already current")
                    return UpdateResult(version, false, "already current")
                }
                tarball = archive
                File(archive.parentFile, archive.name + ".sha256").takeIf { it.isFile }?.let { shaText = it.readText() }
                log("installing from ${archive.name}")
            } else {
                val rel = findRelease(tag)
                version = rel.version
                if (version == store.current && store.currentBinary != null) {
                    log("${rel.tag} is already current")
                    return UpdateResult(version, false, "already current")
                }
                log("found ${rel.tag}: ${rel.name}")
                tarball = File(work, rel.name)
                fetch.download(rel.assetUrl, "application/octet-stream", tarball)
                shaText = rel.shaUrl?.let { String(fetch.get(it, "application/octet-stream")) }
            }
            if (shaText != null) {
                verifySha256(tarball, shaText!!)
                log("checksum ok")
            } else {
                log("no checksum published; trusting the archive")
            }
            val extracted = unpack(tarball, File(work, "x"))
            val binary = File(extracted, "caelza").apply { setExecutable(true, false) }
            val probeConfig = probeConfigCopy(store.configDir, File(work, "probe-config"))
            val probe = prober.probe(binary, version, probeConfig)
            if (!probe.ok) {
                log("probe failed; $version discarded, ${store.current ?: "nothing"} stays current")
                return UpdateResult(version, false, probe.detail, previous = store.current)
            }
            val previous = store.current
            val previousHolds = previous != null && previous != version && store.binary(previous).isFile
            val good = store.lastGood
            val goodHolds = good != null && good != version && store.binary(good).isFile
            store.installVersion(version, extracted)
            if (previousHolds || goodHolds) store.switch(version) else store.promote(version)
            store.installWebDist(File(store.versionDir(version), "web/dist"))
            store.prune(pin = setOfNotNull(previous))
            log("installed $version, current")
            return UpdateResult(version, true, probe.detail, previous = previous, lastGood = store.lastGood)
        } finally {
            work.deleteRecursively()
        }
    }

    companion object {
        const val TARGET = "aarch64-linux-android"
        const val DEFAULT_REPO = "Enlightened-Republic/Caelza"
        const val RELEASES_API = "https://api.github.com/repos"
        private val SEMVER = Regex("""^\d+\.\d+\.\d+\S*$""")
        private val SHA256 = Regex("""^[0-9a-f]{64}$""")

        /** The archive and checksum assets for `target` in one release's JSON. */
        fun parseRelease(json: String, target: String): Release {
            val data = JSONObject(json)
            val tag = data.optString("tag_name", "")
            val suffix = "-$target.tar.gz"
            val assets = data.optJSONArray("assets")
            val byName = LinkedHashMap<String, JSONObject>()
            if (assets != null) for (i in 0 until assets.length()) {
                val a = assets.getJSONObject(i)
                byName[a.optString("name", "")] = a
            }
            val archive = byName.entries.firstOrNull { it.key.endsWith(suffix) }
                ?: throw NoSuchElementException("release ${tag.ifEmpty { "?" }} has no $suffix asset (the Android build is experimental and may have been skipped)")
            val name = archive.key
            val version = versionFromName(name, target) ?: tag.removePrefix("v")
            return Release(
                tag = tag,
                version = version,
                name = name,
                assetUrl = archive.value.getString("url"),
                shaUrl = byName["$name.sha256"]?.optString("url")?.takeIf { it.isNotEmpty() },
            )
        }

        /** `caelza-0.1.0-aarch64-linux-android.tar.gz` → `0.1.0`, the way release.yml names it. */
        fun versionFromName(name: String, target: String): String? {
            val prefix = "caelza-"
            val suffix = "-$target.tar.gz"
            if (!name.startsWith(prefix) || !name.endsWith(suffix) || name.length <= prefix.length + suffix.length) return null
            return name.substring(prefix.length, name.length - suffix.length)
        }

        fun sha256(file: File): String {
            val digest = MessageDigest.getInstance("SHA-256")
            file.inputStream().use { input ->
                val buf = ByteArray(1 shl 20)
                while (true) {
                    val n = input.read(buf)
                    if (n < 0) break
                    digest.update(buf, 0, n)
                }
            }
            return digest.digest().joinToString("") { "%02x".format(it) }
        }

        /** `sha256sum` output (`<hex>  <name>`) against the archive. */
        fun verifySha256(archive: File, shaText: String): String {
            val expected = shaText.trim().split(Regex("\\s+")).firstOrNull()?.lowercase() ?: ""
            if (!SHA256.matches(expected)) throw IllegalArgumentException("checksum file is not a sha256: ${shaText.take(80)}")
            val actual = sha256(archive)
            if (actual != expected) throw IllegalStateException("checksum mismatch for ${archive.name}: expected ${expected.take(12)}…, got ${actual.take(12)}…")
            return actual
        }

        /** Extract a release archive into `into`, refusing a member that escapes it; the directory holding `binaryName`. */
        fun unpack(archive: File, into: File, binaryName: String = "caelza"): File {
            into.mkdirs()
            val root = into.canonicalFile
            GzipCompressorInputStream(archive.inputStream().buffered()).use { gz ->
                TarArchiveInputStream(gz).use { tar ->
                    while (true) {
                        val entry = tar.nextEntry ?: break
                        val name = entry.name
                        if (name.startsWith("/") || name.startsWith("\\") || name.split('/', '\\').contains("..")) {
                            throw IllegalArgumentException("archive member refused: $name")
                        }
                        if (entry.isSymbolicLink || entry.isLink) {
                            val link = entry.linkName
                            if (link.startsWith("/") || link.split('/', '\\').contains("..")) throw IllegalArgumentException("archive member refused: $name")
                            continue  // links are not needed from a release archive
                        }
                        if (entry.isCharacterDevice || entry.isBlockDevice || entry.isFIFO) throw IllegalArgumentException("archive member refused: $name")
                        val out = File(root, name)
                        if (!out.canonicalPath.startsWith(root.path + File.separator) && out.canonicalFile != root) {
                            throw IllegalArgumentException("archive member refused: $name")
                        }
                        if (entry.isDirectory) {
                            out.mkdirs()
                        } else {
                            out.parentFile?.mkdirs()
                            FileOutputStream(out).use { tar.copyTo(it) }
                            if (entry.mode and 0b001_001_001 != 0) out.setExecutable(true, false)
                        }
                    }
                }
            }
            val binary = root.walkTopDown().firstOrNull { it.isFile && it.name == binaryName }
                ?: throw IllegalArgumentException("archive has no $binaryName binary")
            return binary.parentFile!!
        }

        /**
         * A copy of the owner's config for the probe gateway to start on: the
         * live dir belongs to the Runtime that is running (its lock, its data).
         * Null when there is no config (the binary starts on its defaults).
         */
        fun probeConfigCopy(configDir: File, into: File): File? {
            if (!File(configDir, "config.toml").isFile) return null
            into.mkdirs()
            for (name in listOf("config.toml", ".secret_key")) {
                File(configDir, name).takeIf { it.isFile }?.copyTo(File(into, name), overwrite = true)
            }
            for (name in listOf("shared", "agents")) {
                val src = File(configDir, name)
                if (!src.isDirectory) continue
                src.walkTopDown()
                    .onEnter { it.name != "workspace" }
                    .filter { it.isFile && !it.name.endsWith(".db") && !it.name.contains(".db-") && !it.name.contains(".sqlite") }
                    .forEach { f ->
                        val dest = File(into, f.relativeTo(configDir).path)
                        dest.parentFile?.mkdirs()
                        f.copyTo(dest, overwrite = true)
                    }
            }
            return into
        }
    }
}

/**
 * Runs the binary: `caelza --version` must answer with the release's version,
 * then `caelza gateway start -p <port>` must serve `/health` within `timeoutMs`
 * and still be running. The gateway is stopped afterwards.
 */
class ProcessProber(
    private val port: Int = 42619,
    private val timeoutMs: Long = 60_000,
    private val home: File? = null,
) : Prober {
    override fun probe(binary: File, expectVersion: String, configDir: File?): ProbeResult {
        val version = versionOf(binary) ?: return ProbeResult(false, "caelza --version did not answer")
        if (version.substringBefore('+') != expectVersion.substringBefore('+')) {
            return ProbeResult(false, "binary says $version, release says $expectVersion")
        }
        if (Gateway.healthy(port, 1_000)) return ProbeResult(false, "probe port $port is in use (a stale gateway?)")
        val argv = mutableListOf(binary.path, "gateway", "start", "-p", port.toString())
        if (configDir != null) argv += listOf("--config-dir", configDir.path)
        val log = File(binary.parentFile, "probe.log")
        val pb = ProcessBuilder(argv).redirectErrorStream(true).redirectOutput(log)
        home?.let { pb.environment()["HOME"] = it.path }
        val proc = try {
            pb.start()
        } catch (e: Exception) {
            return ProbeResult(false, "could not start the gateway: ${e.message}")
        }
        val deadline = System.currentTimeMillis() + timeoutMs
        var detail = "gateway never answered /health"
        var healthy = false
        try {
            while (System.currentTimeMillis() < deadline) {
                if (!proc.isAlive) {
                    detail = "gateway exited ${proc.exitValue()} before answering /health"
                    break
                }
                if (Gateway.healthy(port, 1_000)) {
                    if (!proc.isAlive) {
                        detail = "gateway exited ${proc.exitValue()} right after answering /health"
                        break
                    }
                    healthy = true
                    break
                }
                Thread.sleep(500)
            }
        } finally {
            if (proc.isAlive) {
                proc.destroy()
                if (!proc.waitFor(5, java.util.concurrent.TimeUnit.SECONDS)) proc.destroyForcibly()
            }
        }
        if (!healthy) {
            val tail = log.takeIf { it.isFile }?.readLines()?.takeLast(20)?.joinToString("\n") ?: ""
            return ProbeResult(false, "$detail\n$tail".trim())
        }
        return ProbeResult(true, "caelza $version answered /health on port $port")
    }

    companion object {
        private val VERSION = Regex("""^caelza\s+(\d+\.\d+\.\d+\S*)""")

        /** `caelza --version` → `0.8.6`, or null when the binary does not answer (or not in time: a hang is killed). */
        fun versionOf(binary: File, timeoutMs: Long = 30_000): String? = try {
            val out = Processes.run(ProcessBuilder(binary.path, "--version"), timeoutMs)
            if (out.exitCode != 0) null else VERSION.find(out.output.trim())?.groupValues?.get(1)
        } catch (_: Exception) {
            null
        }
    }
}
