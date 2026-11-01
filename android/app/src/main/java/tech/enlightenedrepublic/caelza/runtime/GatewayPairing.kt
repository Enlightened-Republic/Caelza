package tech.enlightenedrepublic.caelza.runtime

import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * The app pairs its own gateway (android-app.md §2). The gateway runs with pairing on, so no
 * other app on the phone can call its API on loopback; the shell is one paired device. At
 * startup the gateway writes an admin token owner-only under its data dir; with it, from
 * loopback, the app mints a pairing code (`POST /admin/paircode/new`, the route
 * `caelza gateway get-paircode --new` uses) and pairs (`POST /api/pair`), then keeps the bearer
 * token in its private files. The token outlives restarts (the gateway persists paired tokens
 * into `config.toml`); when it stops working, the app pairs again.
 */
class GatewayPairing(
    private val configDir: File,
    private val tokenFile: File,
    private val http: Http = UrlHttp,
) {
    /** A request's answer: the status (-1 when nothing answered) and the body. */
    data class Reply(val code: Int, val body: String)

    fun interface Http {
        fun send(method: String, url: String, headers: Map<String, String>, body: String?): Reply
    }

    sealed class Outcome {
        /** A token the gateway accepts; `fresh` when this call paired. */
        data class Paired(val token: String, val fresh: Boolean) : Outcome()

        /** Pairing is off for this gateway: nothing to send, the dashboard needs no token. */
        data class Off(val detail: String) : Outcome()

        data class Failed(val detail: String) : Outcome()
    }

    /** Where the gateway writes its admin token: `<config dir>/data/gateway-admin.token`. */
    val adminTokenFile: File get() = File(File(configDir, DATA_DIR), ADMIN_TOKEN_FILE)

    fun storedToken(): String? = tokenFile.takeIf { it.isFile }?.readText()?.trim()?.ifEmpty { null }

    /**
     * A bearer token the gateway on `port` accepts: the stored one when it still works, else a
     * fresh pairing. One at a time across the process: the gateway holds a single pending
     * pairing code, so two callers minting at once (the shell and the service, on the same
     * /health) would have one of them pair with a code the other just replaced.
     */
    fun ensureToken(port: Int): Outcome = synchronized(PAIRING) { ensureTokenLocked(port) }

    private fun ensureTokenLocked(port: Int): Outcome {
        val base = "http://127.0.0.1:$port"
        storedToken()?.let { token ->
            val probe = send("GET", "$base/api/status", mapOf("Authorization" to "Bearer $token"))
            when (probe.code) {
                in 200..299 -> return Outcome.Paired(token, fresh = false)
                401, 403 -> Unit // revoked or the config was reset: pair again
                -1 -> return Outcome.Failed("the gateway does not answer: ${probe.body}")
                else -> return Outcome.Failed("the gateway answered HTTP ${probe.code} to the stored token")
            }
        }
        val admin = adminTokenFile.takeIf { it.isFile }?.readText()?.trim()?.ifEmpty { null }
            ?: return Outcome.Failed("no gateway admin token at ${adminTokenFile.path}: is the gateway running from this app's files?")
        val minted = send("POST", "$base/admin/paircode/new", mapOf(ADMIN_TOKEN_HEADER to admin))
        val mintedJson = minted.json()
        if (minted.code == -1) return Outcome.Failed("the gateway does not answer: ${minted.body}")
        if (minted.code == 400 && mintedJson != null && !mintedJson.optBoolean("pairing_required", true)) {
            return Outcome.Off(mintedJson.optString("message", "pairing is off for this gateway"))
        }
        val code = mintedJson?.optString("pairing_code", "")?.takeIf { it.isNotEmpty() }
            ?: return Outcome.Failed("could not mint a pairing code (HTTP ${minted.code}): ${mintedJson?.optString("message")?.ifEmpty { null } ?: minted.body.take(200)}")
        val pair = send(
            "POST", "$base/api/pair", mapOf("Content-Type" to "application/json"),
            JSONObject().put("code", code).put("device_name", DEVICE_NAME).put("device_type", DEVICE_TYPE).toString(),
        )
        val token = pair.json()?.optString("token", "")?.takeIf { it.isNotEmpty() }
            ?: return Outcome.Failed("pairing failed (HTTP ${pair.code}): ${pair.body.take(200)}")
        tokenFile.parentFile?.mkdirs()
        tokenFile.writeText(token + "\n")
        tokenFile.setReadable(false, false)
        tokenFile.setReadable(true, true)
        return Outcome.Paired(token, fresh = true)
    }

    private fun send(method: String, url: String, headers: Map<String, String>, body: String? = null): Reply = try {
        http.send(method, url, headers, body)
    } catch (e: Exception) {
        Reply(-1, e.message ?: e.toString())
    }

    private fun Reply.json(): JSONObject? = try {
        JSONObject(body)
    } catch (_: Exception) {
        null
    }

    companion object {
        const val DATA_DIR = "data"
        const val ADMIN_TOKEN_FILE = "gateway-admin.token"
        const val ADMIN_TOKEN_HEADER = "x-caelza-admin-token"
        /** The app's bearer token, under its files dir (never under the Runtime's config). */
        const val TOKEN_FILE = "gateway-token"
        const val DEVICE_NAME = "Caelza app (this phone)"
        const val DEVICE_TYPE = "app"
        /** The key the dashboard keeps its token under in localStorage (web/src/lib/auth.ts). */
        const val WEB_TOKEN_KEY = "caelza_token"
        /** Serialises `ensureToken` across every instance in the process (the shell's and the service's). */
        private val PAIRING = Any()

        fun forStore(store: RuntimeStore): GatewayPairing = GatewayPairing(store.configDir, File(store.home, TOKEN_FILE))

        /** JavaScript that hands the token to the dashboard the way its pairing screen would. */
        fun tokenScript(token: String): String =
            "try{localStorage.setItem(${JSONObject.quote(WEB_TOKEN_KEY)},${JSONObject.quote(token)})}catch(e){}"

        object UrlHttp : Http {
            override fun send(method: String, url: String, headers: Map<String, String>, body: String?): Reply {
                val conn = URL(url).openConnection() as HttpURLConnection
                try {
                    conn.connectTimeout = 5_000
                    conn.readTimeout = 15_000
                    conn.requestMethod = method
                    headers.forEach { (k, v) -> conn.setRequestProperty(k, v) }
                    if (body != null) {
                        conn.doOutput = true
                        conn.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
                    }
                    val code = conn.responseCode
                    val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                    val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
                    return Reply(code, text)
                } finally {
                    conn.disconnect()
                }
            }
        }
    }
}
