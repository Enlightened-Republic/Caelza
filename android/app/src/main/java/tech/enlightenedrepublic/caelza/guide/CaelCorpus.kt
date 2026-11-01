package tech.enlightenedrepublic.caelza.guide

import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest

/**
 * Cael's docs corpus: `guide/corpus.jsonl`, bundled as `assets/cael-corpus.jsonl`, the manual
 * the guide answers from. It goes into `agents.cael`'s memory through the gateway's
 * `/api/memory` the way `scripts/cael_corpus.py load` does it (one upsert per chunk, key
 * `docs/<page>#<n>`, category `core`), and the Runtime's per-turn recall puts the matching
 * passages in his context; he needs no tool for it. A marker under the config dir remembers
 * which corpus went in, so each version loads once. A gateway that does not know
 * `agents.cael` yet (the first run not walked) leaves no marker, and the next start tries again.
 */
class CaelCorpus(
    private val configDir: File,
    private val post: (url: String, body: String, token: String?) -> Reply = ::httpPost,
) {
    data class Chunk(val key: String, val content: String)

    /** A post's answer: the status and the body (-1 and the error when nothing answered). */
    data class Reply(val code: Int, val body: String)

    /**
     * What a load did: `loaded` chunks stored, `leftOut` refused by the gateway's content
     * scan (a newer pin's rule; the rest goes in and the marker is written), `failed` for
     * anything else, `skipped` when this corpus was in already.
     */
    data class Result(val loaded: Int, val failed: Int, val skipped: Boolean, val detail: String, val leftOut: Int = 0)

    private val marker: File get() = File(configDir, MARKER)

    /** The fingerprint of the corpus loaded before, if any. */
    fun loadedFingerprint(): String? = marker.takeIf { it.isFile }?.readText()?.trim()?.ifEmpty { null }

    /**
     * Every chunk of `jsonl` into Cael's memory through the gateway on `port`, unless this
     * corpus is already in. `token` is the app's paired bearer (GatewayPairing); null when
     * the gateway runs with pairing off.
     */
    fun load(jsonl: String, port: Int, token: String? = null): Result {
        val fingerprint = fingerprint(jsonl)
        if (loadedFingerprint() == fingerprint) return Result(0, 0, true, "corpus $fingerprint already loaded")
        val chunks = parse(jsonl)
        var loaded = 0
        var failed = 0
        var leftOut = 0
        var detail = ""
        for (chunk in chunks) {
            val body = JSONObject()
                .put("key", chunk.key)
                .put("content", chunk.content)
                .put("category", CATEGORY)
                .put("agent", AGENT)
                .toString()
            val reply = try {
                post(url(port), body, token)
            } catch (e: Exception) {
                Reply(-1, e.message ?: e.toString())
            }
            val code = reply.code
            if (code in 200..299) {
                loaded++
                continue
            }
            if (code == 500 && reply.body.contains(SCAN_BLOCKED)) {
                leftOut++
                continue
            }
            failed++
            detail = when (code) {
                400 -> "the gateway does not know agents.$AGENT yet (HTTP 400 at ${chunk.key}); the first run creates him"
                401, 403 -> "the gateway refused the store (HTTP $code at ${chunk.key})"
                -1 -> "the gateway stopped answering at ${chunk.key}"
                else -> "HTTP $code at ${chunk.key}"
            }
            if (code == 400 || code == 401 || code == 403 || code == -1) break
        }
        if (failed == 0) {
            marker.parentFile?.mkdirs()
            marker.writeText(fingerprint + "\n")
            detail = "corpus $fingerprint loaded: $loaded chunks" + if (leftOut > 0) ", $leftOut left out by the gateway's content scan" else ""
        }
        return Result(loaded, failed, false, detail, leftOut)
    }

    companion object {
        const val ASSET = "cael-corpus.jsonl"
        const val MARKER = "cael-corpus.loaded"
        const val AGENT = "cael"
        const val CATEGORY = "core"
        /** What the gateway answers when its memory write scanner refuses a chunk (scripts/cael_corpus.py SCAN_BLOCKED). */
        const val SCAN_BLOCKED = "blocked by content scan"

        fun url(port: Int): String = "http://127.0.0.1:$port/api/memory"

        fun parse(jsonl: String): List<Chunk> = jsonl.lineSequence()
            .filter { it.isNotBlank() }
            .map { JSONObject(it) }
            .map { Chunk(it.getString("key"), it.getString("content")) }
            .toList()

        /** The first 16 hex digits of the corpus's SHA-256: enough to tell versions apart. */
        fun fingerprint(jsonl: String): String =
            MessageDigest.getInstance("SHA-256").digest(jsonl.toByteArray(Charsets.UTF_8))
                .joinToString("") { "%02x".format(it) }.substring(0, 16)

        fun httpPost(url: String, body: String, token: String?): Reply {
            val conn = URL(url).openConnection() as HttpURLConnection
            try {
                conn.connectTimeout = 5_000
                conn.readTimeout = 30_000
                conn.requestMethod = "POST"
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", "application/json")
                if (token != null) conn.setRequestProperty("Authorization", "Bearer $token")
                conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                return Reply(code, stream?.bufferedReader()?.use { it.readText() } ?: "")
            } finally {
                conn.disconnect()
            }
        }
    }
}
