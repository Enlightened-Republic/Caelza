package tech.enlightenedrepublic.caelza.model

import org.json.JSONObject
import java.io.Closeable
import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import java.io.InputStream
import java.net.HttpURLConnection
import java.net.URL
import java.nio.file.Files
import java.nio.file.StandardCopyOption
import java.security.MessageDigest

/** One ranged GET; a seam so the tests hand the store a canned server, a cut stream, a tampered file. */
fun interface Downloader {
    /** Open `url` from byte `from`. `resumed` false means the server ignored the range and starts at 0. */
    fun open(url: String, from: Long): Download
}

class Download(val stream: InputStream, val resumed: Boolean, val total: Long?) : Closeable {
    override fun close() = stream.close()
}

/** `HttpURLConnection` with a `Range` header; a 206 resumes, a 200 starts over. Redirects (Hugging Face's CDN) are followed. */
class HttpDownloader : Downloader {
    override fun open(url: String, from: Long): Download {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = 20_000
        conn.readTimeout = 60_000
        conn.instanceFollowRedirects = true
        conn.setRequestProperty("User-Agent", "caelza-android model store")
        if (from > 0) conn.setRequestProperty("Range", "bytes=$from-")
        val code = conn.responseCode
        if (code !in 200..299) {
            conn.disconnect()
            throw IllegalStateException("HTTP $code for $url")
        }
        val resumed = code == 206
        val length = conn.contentLengthLong
        val total = if (length < 0) null else if (resumed) from + length else length
        return Download(conn.inputStream, resumed, total)
    }
}

/**
 * A download that must be whole and must match a pinned sha256 (`model-setup.sh`'s
 * `fetch_gguf`): resumable through a `.part` file, hashed as it streams (the
 * bytes already on disk are hashed first on a resume), retried on a cut
 * connection, and never trusted on a mismatch.
 */
object VerifiedDownload {
    const val ATTEMPTS = 5

    /** Destinations being written right now: a second fetch of the same file would interleave bytes into its `.part`. */
    private val inFlight: MutableSet<String> = java.util.Collections.synchronizedSet(mutableSetOf())

    fun fetch(
        url: String,
        sha256: String,
        bytes: Long,
        dest: File,
        downloader: Downloader,
        progress: (done: Long, total: Long) -> Unit = { _, _ -> },
        attempts: Int = ATTEMPTS,
    ): File {
        check(inFlight.add(dest.absolutePath)) { "${dest.name} is already being downloaded" }
        try {
            return fetchAlone(url, sha256, bytes, dest, downloader, progress, attempts)
        } finally {
            inFlight.remove(dest.absolutePath)
        }
    }

    private fun fetchAlone(
        url: String,
        sha256: String,
        bytes: Long,
        dest: File,
        downloader: Downloader,
        progress: (done: Long, total: Long) -> Unit,
        attempts: Int,
    ): File {
        dest.parentFile?.mkdirs()
        val part = File(dest.parentFile, dest.name + ".part")
        var lastError: IOException? = null
        for (attempt in 1..attempts) {
            try {
                val digest = MessageDigest.getInstance("SHA-256")
                var have = if (part.isFile) part.length() else 0L
                if (have > bytes) {
                    part.delete()
                    have = 0
                }
                if (have == bytes && have > 0) {
                    // Whole already (the process died between the last write and the rename):
                    // verify it with no request at all; a range past the end would only earn a 416.
                    hashInto(digest, part)
                    if (hex(digest) == sha256) {
                        Files.move(part.toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
                        return dest
                    }
                    part.delete()
                    have = 0
                    digest.reset()
                }
                if (have > 0) hashInto(digest, part)
                downloader.open(url, have).use { dl ->
                    if (have > 0 && !dl.resumed) {
                        digest.reset()
                        have = 0
                    }
                    FileOutputStream(part, have > 0).use { out ->
                        val buf = ByteArray(1 shl 16)
                        var done = have
                        progress(done, bytes)
                        while (true) {
                            val n = dl.stream.read(buf)
                            if (n < 0) break
                            out.write(buf, 0, n)
                            digest.update(buf, 0, n)
                            done += n
                            progress(done, bytes)
                        }
                    }
                }
                if (part.length() != bytes) throw IOException("short download: ${part.length()} of $bytes bytes")
                val actual = hex(digest)
                if (actual != sha256) {
                    part.delete()
                    throw IllegalStateException("checksum mismatch for ${dest.name}: expected ${sha256.take(12)}…, got ${actual.take(12)}…")
                }
                Files.move(part.toPath(), dest.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
                return dest
            } catch (e: IOException) {
                lastError = e
                if (attempt == attempts) throw e
            }
        }
        throw lastError ?: IOException("download failed")
    }

    private fun hex(digest: MessageDigest): String = digest.digest().joinToString("") { "%02x".format(it) }

    private fun hashInto(digest: MessageDigest, file: File) {
        file.inputStream().use { input ->
            val buf = ByteArray(1 shl 20)
            while (true) {
                val n = input.read(buf)
                if (n < 0) break
                digest.update(buf, 0, n)
            }
        }
    }
}

/** What llama-server serves, the app's `serve.sh`: written by the first run, read by the service. */
data class ModelServe(val model: String, val port: Int = ModelLadder.SERVER_PORT, val ctx: Int = ModelLadder.CONTEXT) {
    fun toJson(): JSONObject = JSONObject().put("model", model).put("port", port).put("ctx", ctx)

    companion object {
        const val FILE = "serve.json"

        fun fromJson(text: String): ModelServe? = try {
            val o = JSONObject(text)
            ModelServe(o.getString("model"), o.optInt("port", ModelLadder.SERVER_PORT), o.optInt("ctx", ModelLadder.CONTEXT))
        } catch (_: Exception) {
            null
        }
    }
}

/**
 * The GGUFs under `<config dir>/models`, where `~/.caelza/models` is on a
 * Termux phone: each verified once against its pin (a marker beside the file
 * holds the sha256, so a gigabyte is not re-hashed on every start), plus the
 * `serve.json` that says which one llama-server loads.
 */
class ModelStore(val dir: File) {
    fun file(g: ModelLadder.Gguf): File = File(dir, g.file)

    private fun marker(g: ModelLadder.Gguf): File = File(dir, g.file + ".sha256")

    /** Present, the pinned size, and verified once. */
    fun verified(g: ModelLadder.Gguf): Boolean {
        val f = file(g)
        return f.isFile && f.length() == g.bytes && marker(g).takeIf { it.isFile }?.readText()?.trim() == g.sha256
    }

    /** Download and verify `g` unless it is already here and verified. */
    fun download(g: ModelLadder.Gguf, downloader: Downloader, progress: (Long, Long) -> Unit = { _, _ -> }): File {
        dir.mkdirs()
        if (verified(g)) {
            progress(g.bytes, g.bytes)
            return file(g)
        }
        val f = VerifiedDownload.fetch(g.url, g.sha256, g.bytes, file(g), downloader, progress)
        marker(g).writeText(g.sha256 + "\n")
        return f
    }

    val serveFile: File get() = File(dir, ModelServe.FILE)

    fun serve(): ModelServe? = serveFile.takeIf { it.isFile }?.let { ModelServe.fromJson(it.readText()) }

    fun writeServe(serve: ModelServe) {
        dir.mkdirs()
        serveFile.writeText(serve.toJson().toString() + "\n")
    }

    fun clearServe() {
        serveFile.delete()
    }

    companion object {
        const val DIR = "models"
    }
}
