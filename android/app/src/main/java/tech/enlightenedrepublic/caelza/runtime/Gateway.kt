package tech.enlightenedrepublic.caelza.runtime

import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/** The Runtime's gateway on loopback: its port from the config, and whether it answers. */
object Gateway {
    private val PORT_LINE = Regex("""^\s*port\s*=\s*(\d+)""", RegexOption.MULTILINE)
    private val SECTION = Regex("""^\s*\[([^\]]+)]""", RegexOption.MULTILINE)

    /** `[gateway] port` from `config.toml`, else the default. */
    fun port(configDir: File): Int {
        val text = File(configDir, "config.toml").takeIf { it.isFile }?.readText() ?: return RuntimeStore.GATEWAY_PORT
        var section = ""
        for (line in text.lines()) {
            SECTION.find(line)?.let { section = it.groupValues[1].trim() }
            if (section == "gateway") {
                PORT_LINE.find(line)?.let { return it.groupValues[1].toIntOrNull() ?: RuntimeStore.GATEWAY_PORT }
            }
        }
        return RuntimeStore.GATEWAY_PORT
    }

    fun url(port: Int, path: String = "/"): String = "http://127.0.0.1:$port$path"

    /**
     * Is `url` on the gateway's own origin, scheme, host and port all three? The shell's
     * WebView hands its paired token only to this origin and opens every other one in
     * the browser, so a link in a chat can never take the dashboard, or the token, elsewhere.
     */
    fun own(url: String?, port: Int): Boolean {
        val u = try {
            java.net.URI(url ?: return false)
        } catch (_: Exception) {
            return false
        }
        return u.scheme == "http" && u.host == "127.0.0.1" && u.port == port
    }

    /** Does `/health` answer 200 within `timeoutMs`? */
    fun healthy(port: Int, timeoutMs: Int = 2_000): Boolean = try {
        val conn = URL(url(port, "/health")).openConnection() as HttpURLConnection
        conn.connectTimeout = timeoutMs
        conn.readTimeout = timeoutMs
        conn.requestMethod = "GET"
        val ok = conn.responseCode in 200..299
        conn.disconnect()
        ok
    } catch (_: Exception) {
        false
    }
}
