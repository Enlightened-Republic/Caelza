package tech.enlightenedrepublic.caelza.runtime

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.compressors.gzip.GzipCompressorOutputStream
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.ServerSocket

/**
 * The guard's pipeline in the app, driven by a fake release: JSON plus a
 * tarball holding a fake `caelza` (a shell script) that answers `--version`
 * and serves `/health` through python3, and can crash or lie instead. The
 * probe is the real ProcessProber on a free port.
 */
class ReleaseInstallerTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val target = "x86_64-unknown-linux-gnu"

    private fun fakeCaelza(version: String, mode: String): String = """
        |#!/bin/sh
        |MODE="$mode"
        |case "${'$'}1" in
        |  --version)
        |    if [ "${'$'}MODE" = "bad-version" ]; then echo "caelza 9.9.9 (v9.9.9+fake)"; else echo "caelza $version (v$version+fake)"; fi
        |    exit 0 ;;
        |  gateway)
        |    [ "${'$'}MODE" = "crash" ] && { echo boom; exit 3; }
        |    shift 2
        |    port="${'$'}2"
        |    exec python3 -c 'import http.server, socketserver, sys
        |class H(http.server.BaseHTTPRequestHandler):
        |    def do_GET(self):
        |        self.send_response(200); self.end_headers(); self.wfile.write(b"ok")
        |    def log_message(self, *a): pass
        |socketserver.TCPServer.allow_reuse_address = True
        |socketserver.TCPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()' "${'$'}port" ;;
        |  daemon) exec sleep 3600 ;;
        |esac
        |""".trimMargin()

    /** A release tarball the way release.yml packs one, and its sha256 line. */
    private fun makeArchive(dir: File, version: String, mode: String = "ok", escaping: Boolean = false): Pair<File, String> {
        val name = "caelza-$version-$target"
        dir.mkdirs()
        val archive = File(dir, "$name.tar.gz")
        TarArchiveOutputStream(GzipCompressorOutputStream(archive.outputStream())).use { tar ->
            tar.setLongFileMode(TarArchiveOutputStream.LONGFILE_GNU)
            fun add(path: String, content: String, mode: Int = 0b110_100_100) {
                val bytes = content.toByteArray()
                val entry = TarArchiveEntry(path).apply { size = bytes.size.toLong(); this.mode = mode }
                tar.putArchiveEntry(entry)
                tar.write(bytes)
                tar.closeArchiveEntry()
            }
            add("$name/caelza", fakeCaelza(version, mode), 0b111_101_101)
            add("$name/web/dist/index.html", "<html>caelza $version</html>")
            add("$name/NOTICE", "notices\n")
            if (escaping) add("$name/../../escape", "x")
        }
        return archive to "${ReleaseInstaller.sha256(archive)}  ${archive.name}\n"
    }

    private fun releaseJson(version: String, withSha: Boolean = true): String {
        val name = "caelza-$version-$target.tar.gz"
        val assets = JSONArray()
            .put(JSONObject().put("name", name).put("url", "api://asset/$name"))
            .put(JSONObject().put("name", "caelza-$version-aarch64-linux-android.tar.gz").put("url", "api://asset/android"))
        if (withSha) assets.put(JSONObject().put("name", "$name.sha256").put("url", "api://asset/$name.sha256"))
        return JSONObject().put("tag_name", "v$version").put("assets", assets).toString()
    }

    /** A canned GitHub: the release JSON and its assets by URL. */
    private inner class CannedGitHub(version: String, archive: File, sha: String, tagOnly: Boolean = false) : Fetch {
        val calls = mutableListOf<Pair<String, String>>()
        val urls = mutableMapOf(
            "${ReleaseInstaller.RELEASES_API}/${ReleaseInstaller.DEFAULT_REPO}/releases/latest" to releaseJson(version).toByteArray(),
            "${ReleaseInstaller.RELEASES_API}/${ReleaseInstaller.DEFAULT_REPO}/releases/tags/v$version" to releaseJson(version).toByteArray(),
            "api://asset/${archive.name}" to archive.readBytes(),
            "api://asset/${archive.name}.sha256" to sha.toByteArray(),
        )

        init {
            if (tagOnly) urls.remove("${ReleaseInstaller.RELEASES_API}/${ReleaseInstaller.DEFAULT_REPO}/releases/latest")
        }

        override fun get(url: String, accept: String): ByteArray {
            calls += url to accept
            return urls[url] ?: throw IllegalStateException("HTTP 404 for $url")
        }
    }

    private fun freePort(): Int = ServerSocket(0).use { it.localPort }

    private fun store() = RuntimeStore(File(tmp.root, "home"))

    @Test
    fun release_parsing_picks_the_target_s_archive_and_checksum() {
        val rel = ReleaseInstaller.parseRelease(releaseJson("0.1.0"), target)
        assertEquals("v0.1.0", rel.tag)
        assertEquals("0.1.0", rel.version)
        assertEquals("caelza-0.1.0-$target.tar.gz", rel.name)
        assertTrue(rel.assetUrl.endsWith("$target.tar.gz"))
        assertTrue(rel.shaUrl!!.endsWith(".sha256"))
        assertNull(ReleaseInstaller.parseRelease(releaseJson("0.1.0", withSha = false), target).shaUrl)
        val missing = assertThrows(NoSuchElementException::class.java) {
            ReleaseInstaller.parseRelease(releaseJson("0.1.0"), "riscv64-unknown-linux-gnu")
        }
        assertTrue(missing.message!!.contains("no -riscv64-unknown-linux-gnu.tar.gz asset"))
        assertEquals("0.1.0", ReleaseInstaller.versionFromName("caelza-0.1.0-aarch64-linux-android.tar.gz", "aarch64-linux-android"))
        assertEquals("0.2.0-rc1", ReleaseInstaller.versionFromName("caelza-0.2.0-rc1-x86_64-unknown-linux-gnu.tar.gz", "x86_64-unknown-linux-gnu"))
        assertNull(ReleaseInstaller.versionFromName("caelza-0.1.0-x86_64-unknown-linux-gnu.tar.gz", "aarch64-linux-android"))
    }

    @Test
    fun checksum_and_unpack_refuse_what_they_should() {
        val (archive, sha) = makeArchive(File(tmp.root, "a"), "0.1.0")
        assertEquals(ReleaseInstaller.sha256(archive), ReleaseInstaller.verifySha256(archive, sha))
        assertThrows(IllegalStateException::class.java) { ReleaseInstaller.verifySha256(archive, "0".repeat(64) + "  x.tar.gz\n") }
        assertThrows(IllegalArgumentException::class.java) { ReleaseInstaller.verifySha256(archive, "not a checksum") }
        val top = ReleaseInstaller.unpack(archive, File(tmp.root, "x"))
        assertTrue(File(top, "caelza").isFile && File(top, "caelza").canExecute())
        assertTrue(File(top, "web/dist/index.html").isFile)
        val (bad, _) = makeArchive(File(tmp.root, "bad"), "0.1.0", escaping = true)
        val refused = assertThrows(IllegalArgumentException::class.java) { ReleaseInstaller.unpack(bad, File(tmp.root, "y")) }
        assertTrue(refused.message!!.startsWith("archive member refused"))
        assertFalse(File(tmp.root, "escape").exists())
    }

    @Test
    fun update_installs_a_release_that_probes_ok_keeps_last_good_on_what_ran_and_discards_one_that_crashes() {
        val s = store()
        s.configDir.mkdirs()
        File(s.configDir, "config.toml").writeText("schema_version = 3\n")
        File(s.configDir, ".secret_key").writeBytes(ByteArray(32) { 1 })
        File(s.configDir, "agents/main/workspace").mkdirs()
        File(s.configDir, "agents/main/SOUL.md").writeText("Cael\n")
        File(s.configDir, "agents/main/workspace/big.bin").writeBytes(ByteArray(10))
        File(s.configDir, "data").mkdirs()
        File(s.configDir, "data/config-lifecycle.lock").writeText("")
        val probed = mutableListOf<Triple<File, String, File?>>()
        val realProber = ProcessProber(port = freePort(), timeoutMs = 20_000)
        val spy = Prober { binary, expect, config ->
            probed += Triple(binary, expect, config?.let { c -> File(c, "snapshot").apply { writeText(c.walkTopDown().filter { it.isFile }.map { it.relativeTo(c).path }.sorted().joinToString("\n")) } }?.let { config })
            realProber.probe(binary, expect, config)
        }
        val lines = mutableListOf<String>()

        val (first, sha1) = makeArchive(File(tmp.root, "a"), "0.1.0")
        var github = CannedGitHub("0.1.0", first, sha1)
        var result = ReleaseInstaller(s, github, spy, target, log = { lines += it }).update()
        assertTrue(result.detail, result.promoted)
        assertEquals("0.1.0", s.current)
        assertEquals("0.1.0", s.lastGood)
        assertEquals("0.1.0", result.lastGood)
        assertTrue(File(s.webDist, "index.html").readText().contains("0.1.0"))
        assertTrue(lines.any { it == "checksum ok" } && lines.any { it.startsWith("found v0.1.0") })
        assertTrue("probed in the work dir, before anything is installed", probed.last().first.path.startsWith(File(s.home, "tmp").path))
        val copy = probed.last().third!!
        assertTrue("probed on a copy of the config", copy.path.startsWith(File(s.home, "tmp").path))
        assertEquals(github.calls.last().second, "application/octet-stream")
        assertTrue(File(s.home, "tmp").listFiles().isNullOrEmpty())
        // The copy carried the config, the key, the agent's files minus its workspace, and no data.
        val snapshot = File(copy, "snapshot")
        assertFalse(snapshot.exists())  // the work dir is gone with the copy
        assertEquals("already current", ReleaseInstaller(s, github, spy, target).update().detail)

        val (second, sha2) = makeArchive(File(tmp.root, "b"), "0.2.0")
        github = CannedGitHub("0.2.0", second, sha2)
        result = ReleaseInstaller(s, github, spy, target).update()
        assertTrue(result.detail, result.promoted)
        assertEquals("0.2.0", s.current)
        assertEquals("the supervisor promotes once it holds", "0.1.0", s.lastGood)
        assertEquals("0.1.0", result.previous)
        assertEquals(listOf("0.1.0", "0.2.0"), s.installed())

        val (crashing, sha3) = makeArchive(File(tmp.root, "c"), "0.3.0", mode = "crash")
        result = ReleaseInstaller(s, CannedGitHub("0.3.0", crashing, sha3), spy, target).update()
        assertFalse(result.promoted)
        assertTrue(result.detail, result.detail.contains("exited 3 before answering /health") && result.detail.contains("boom"))
        assertEquals("0.2.0", s.current)
        assertEquals(listOf("0.1.0", "0.2.0"), s.installed())

        val (lying, sha4) = makeArchive(File(tmp.root, "d"), "0.4.0", mode = "bad-version")
        result = ReleaseInstaller(s, CannedGitHub("0.4.0", lying, sha4), spy, target).update()
        assertFalse(result.promoted)
        assertEquals("binary says 9.9.9, release says 0.4.0", result.detail)

        // A tampered archive never reaches the probe.
        val before = probed.size
        assertThrows(IllegalStateException::class.java) {
            ReleaseInstaller(s, CannedGitHub("0.3.0", crashing, "0".repeat(64) + "  x\n"), spy, target).update()
        }
        assertEquals(before, probed.size)

        // A local archive needs no network; a bare version as the tag means the v-tag.
        val (local, sha5) = makeArchive(File(tmp.root, "e"), "0.5.0")
        File(local.parentFile, local.name + ".sha256").writeText(sha5)
        val noNetwork = Fetch { url, _ -> throw AssertionError("network call: $url") }
        result = ReleaseInstaller(s, noNetwork, spy, target).update(archive = local)
        assertTrue(result.promoted)
        assertEquals("0.5.0", s.current)
        val tagged = CannedGitHub("0.6.0", local, sha5, tagOnly = true)
        assertThrows(IllegalStateException::class.java) { ReleaseInstaller(s, tagged, spy, target).update(tag = "9.9.9") }
        assertTrue(tagged.calls.last().first.endsWith("/releases/tags/v9.9.9"))
    }

    @Test
    fun the_probe_config_copy_carries_the_config_not_the_data() {
        val cfg = File(tmp.root, ".caelza").apply { mkdirs() }
        assertNull(ReleaseInstaller.probeConfigCopy(cfg, File(tmp.root, "copy0")))
        File(cfg, "config.toml").writeText("schema_version = 3\n")
        File(cfg, ".secret_key").writeBytes(ByteArray(32) { 1 })
        File(cfg, "shared/sops/phone-debloat").mkdirs()
        File(cfg, "shared/sops/phone-debloat/SOP.toml").writeText("[sop]\n")
        File(cfg, "agents/main/workspace").mkdirs()
        File(cfg, "agents/main/SOUL.md").writeText("Cael\n")
        File(cfg, "agents/main/workspace/big.bin").writeBytes(ByteArray(10))
        File(cfg, "agents/main/memory.db").writeBytes(ByteArray(10))
        File(cfg, "data").mkdirs()
        File(cfg, "data/config-lifecycle.lock").writeText("")
        val copy = ReleaseInstaller.probeConfigCopy(cfg, File(tmp.root, "copy"))!!
        val files = copy.walkTopDown().filter { it.isFile }.map { it.relativeTo(copy).path }.sorted().toList()
        assertEquals(listOf(".secret_key", "agents/main/SOUL.md", "config.toml", "shared/sops/phone-debloat/SOP.toml"), files)
    }

    @Test
    fun the_prober_refuses_a_busy_port_and_a_binary_that_does_not_answer() {
        val (archive, _) = makeArchive(File(tmp.root, "a"), "0.1.0")
        val binary = File(ReleaseInstaller.unpack(archive, File(tmp.root, "x")), "caelza")
        assertEquals("0.1.0", ProcessProber.versionOf(binary))
        assertNull(ProcessProber.versionOf(File(tmp.root, "nope")))
        assertEquals(ProbeResult(false, "caelza --version did not answer"), ProcessProber(port = freePort()).probe(File(tmp.root, "nope"), "0.1.0", null))
        val taken = ServerSocket(0, 1, java.net.InetAddress.getByName("127.0.0.1"))
        try {
            // Something answers on the port: the prober must not take that for the new binary.
            val port = taken.localPort
            val serving = Thread {
                try {
                    val sock = taken.accept()
                    sock.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok".toByteArray())
                    sock.close()
                } catch (_: Exception) {
                }
            }.apply { isDaemon = true; start() }
            val result = ProcessProber(port = port, timeoutMs = 5_000).probe(binary, "0.1.0", null)
            assertFalse(result.ok)
            assertTrue(result.detail, result.detail.startsWith("probe port $port is in use"))
            serving.join(2_000)
        } finally {
            taken.close()
        }
    }
}
