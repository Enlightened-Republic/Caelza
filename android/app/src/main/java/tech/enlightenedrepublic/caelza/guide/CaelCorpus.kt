package tech.enlightenedrepublic.caelza.guide

import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.security.MessageDigest

/**
 * Cael's docs corpus: `guide/corpus.jsonl`, bundled as `assets/cael-corpus.jsonl`, the manual
 * the guide answers from. It goes into `agents.cael`'s memory through the gateway's
 * `/api/memory` the way `scripts/cael_corpus.py load --prune` does it (one upsert per chunk,
 * key `docs/<page>#<n>`, category `core`, then the `docs/` keys an older corpus left are
 * deleted), and the Runtime's per-turn recall puts the matching passages in his context; he
 * needs no tool for it. A marker under the config dir remembers which corpus went in, so each
 * version loads once. A gateway that does not know `agents.cael` yet (the first run not
 * walked) leaves no marker, and the next start tries again.
 */
class CaelCorpus(
    private val configDir: File,
    private val http: (method: String, url: String, body: String?, token: String?) -> Reply = ::httpCall,
) {
    data class Chunk(val key: String, val content: String)

    /** A request's answer: the status and the body (-1 and the error when nothing answered). */
    data class Reply(val code: Int, val body: String)

    /**
     * What a load did: `loaded` chunks stored, `leftOut` refused by the gateway's content
     * scan (a newer pin's rule; the rest goes in and the marker is written), `failed` for
     * anything else, `pruned` stale chunks of an older corpus deleted, `skipped` when this
     * corpus was in already.
     */
    data class Result(
        val loaded: Int,
        val failed: Int,
        val skipped: Boolean,
        val detail: String,
        val leftOut: Int = 0,
        val pruned: Int = 0,
    )

    private val marker: File get() = File(configDir, MARKER)

    /** The fingerprint of the corpus loaded before, if any. */
    fun loadedFingerprint(): String? = marker.takeIf { it.isFile }?.readText()?.trim()?.ifEmpty { null }

    /**
     * Every chunk of `jsonl` into Cael's memory through the gateway on `port`, unless this
     * corpus is already in; then the `docs/` chunks the bundled corpus no longer carries are
     * deleted (keys are dense per page, so a page that shrank leaves a stale tail otherwise).
     * `token` is the app's paired bearer (GatewayPairing); null when the gateway runs with
     * pairing off.
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
            val reply = call("POST", url(port), body, token)
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
            // A gateway that keeps failing stores is not worth a request per chunk at every start.
            if (failed >= MAX_FAILURES) {
                detail += "; gave up after $MAX_FAILURES failures"
                break
            }
        }
        if (failed > 0) return Result(loaded, failed, false, detail, leftOut)
        val pruned = prune(port, token, chunks.map { it.key }.toSet())
        marker.parentFile?.mkdirs()
        marker.writeText(fingerprint + "\n")
        detail = "corpus $fingerprint loaded: $loaded chunks" +
            (if (leftOut > 0) ", $leftOut left out by the gateway's content scan" else "") +
            (if (pruned.count > 0) ", ${pruned.count} stale chunks pruned" else "") +
            (pruned.problem?.let { "; prune: $it" } ?: "")
        return Result(loaded, failed, false, detail, leftOut, pruned.count)
    }

    private data class Pruned(val count: Int, val problem: String?)

    /**
     * `GET /api/memory?agent=cael&category=core`, then `DELETE /api/memory/<key>?agent=cael`
     * for every `docs/` key not in `keep` (`cael_corpus.py load --prune`). A prune that fails
     * is reported, not fatal: the corpus is in, the stale tail only costs recall slots.
     */
    private fun prune(port: Int, token: String?, keep: Set<String>): Pruned {
        val listed = call("GET", "${url(port)}?agent=$AGENT&category=$CATEGORY", null, token)
        if (listed.code !in 200..299) return Pruned(0, "could not list Cael's memory (HTTP ${listed.code})")
        val keys = try {
            val entries = JSONObject(listed.body).optJSONArray("entries") ?: return Pruned(0, null)
            (0 until entries.length()).mapNotNull { entries.optJSONObject(it)?.optString("key") }
        } catch (e: Exception) {
            return Pruned(0, "could not read the memory list: ${e.message}")
        }
        var count = 0
        for (key in keys.filter { it.startsWith(KEY_PREFIX) && it !in keep }.sorted()) {
            val gone = call("DELETE", "${url(port)}/${URLEncoder.encode(key, "UTF-8")}?agent=$AGENT", null, token)
            if (gone.code !in 200..299) return Pruned(count, "HTTP ${gone.code} deleting $key")
            count++
        }
        return Pruned(count, null)
    }

    private fun call(method: String, url: String, body: String?, token: String?): Reply = try {
        http(method, url, body, token)
    } catch (e: Exception) {
        Reply(-1, e.message ?: e.toString())
    }

    companion object {
        const val ASSET = "cael-corpus.jsonl"
        const val MARKER = "cael-corpus.loaded"
        const val AGENT = "cael"
        const val CATEGORY = "core"
        /** The corpus's keys, `docs/<page>#<n>` (scripts/cael_corpus.py KEY_PREFIX); nothing else is pruned. */
        const val KEY_PREFIX = "docs/"
        /** What the gateway answers when its memory write scanner refuses a chunk (scripts/cael_corpus.py SCAN_BLOCKED). */
        const val SCAN_BLOCKED = "blocked by content scan"
        /** Stores that fail for another reason stop the load after this many. */
        const val MAX_FAILURES = 3

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

        fun httpCall(method: String, url: String, body: String?, token: String?): Reply {
            val conn = URL(url).openConnection() as HttpURLConnection
            try {
                conn.connectTimeout = 5_000
                conn.readTimeout = 30_000
                conn.requestMethod = method
                if (token != null) conn.setRequestProperty("Authorization", "Bearer $token")
                if (body != null) {
                    conn.doOutput = true
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                }
                val code = conn.responseCode
                val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                return Reply(code, stream?.bufferedReader()?.use { it.readText() } ?: "")
            } finally {
                conn.disconnect()
            }
        }
    }
}
