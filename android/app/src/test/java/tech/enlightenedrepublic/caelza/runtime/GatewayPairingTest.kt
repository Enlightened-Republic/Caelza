package tech.enlightenedrepublic.caelza.runtime

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.BufferedReader
import java.io.File
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import kotlin.concurrent.thread

/**
 * The app pairing its own gateway, against a fake one on loopback: the admin token mints a
 * code, the code pairs, the token is kept and reused, a revoked token pairs again, and the
 * ways it cannot (no admin token, pairing off, nothing listening) are told apart.
 */
class GatewayPairingTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private class Request(val method: String, val path: String, val headers: Map<String, String>, val body: String)

    /**
     * /api/status (bearer-gated), /admin/paircode/new (admin-token-gated) and /api/pair, like the
     * gateway; a few lines of HTTP/1.1 over a ServerSocket, since the JDK's HttpServer is not on
     * the unit-test classpath.
     */
    private class FakeGateway(private val adminToken: String, @Volatile var pairingOn: Boolean = true) : AutoCloseable {
        private val socket = ServerSocket(0, 8, InetAddress.getByName("127.0.0.1"))
        val port: Int get() = socket.localPort
        val tokens = mutableSetOf<String>()
        val codes = mutableSetOf<String>()
        @Volatile var mints = 0
        val pairs = mutableListOf<JSONObject>()

        init {
            thread(isDaemon = true, name = "fake-gateway") {
                while (!socket.isClosed) {
                    val client = try { socket.accept() } catch (_: Exception) { break }
                    thread(isDaemon = true) { client.use { serve(it) } }
                }
            }
        }

        private fun read(s: Socket): Request {
            val reader = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
            val line = reader.readLine() ?: return Request("", "", emptyMap(), "")
            val parts = line.split(" ")
            val headers = mutableMapOf<String, String>()
            while (true) {
                val h = reader.readLine() ?: break
                if (h.isEmpty()) break
                val i = h.indexOf(':')
                if (i > 0) headers[h.substring(0, i).trim().lowercase()] = h.substring(i + 1).trim()
            }
            val length = headers["content-length"]?.toIntOrNull() ?: 0
            val buf = CharArray(length)
            var got = 0
            while (got < length) {
                val n = reader.read(buf, got, length - got)
                if (n < 0) break
                got += n
            }
            return Request(parts.getOrElse(0) { "" }, parts.getOrElse(1) { "" }, headers, String(buf, 0, got))
        }

        private fun serve(s: Socket) {
            val req = read(s)
            val (code, body) = synchronized(this) { answer(req) }
            val bytes = body.toByteArray(Charsets.UTF_8)
            val head = "HTTP/1.1 $code ${if (code == 200) "OK" else "Error"}\r\nContent-Type: application/json\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n"
            s.getOutputStream().apply { write(head.toByteArray(Charsets.UTF_8)); write(bytes); flush() }
        }

        private fun answer(req: Request): Pair<Int, String> = when {
            req.path == "/api/status" -> {
                val bearer = req.headers["authorization"]?.removePrefix("Bearer ")
                if (!pairingOn || bearer in tokens) 200 to """{"version":"0.1.0"}""" else 401 to """{"error":"Unauthorized"}"""
            }
            req.path == "/admin/paircode/new" -> when {
                req.method != "POST" -> 405 to "{}"
                req.headers[GatewayPairing.ADMIN_TOKEN_HEADER] != adminToken -> 401 to """{"success":false,"error":"admin token"}"""
                !pairingOn -> 400 to """{"success":false,"pairing_required":false,"pairing_code":null,"message":"Pairing is disabled for this gateway"}"""
                else -> {
                    mints++
                    val code = "CODE-$mints"
                    codes += code
                    200 to """{"success":true,"pairing_required":true,"pairing_code":"$code","message":"New pairing code generated"}"""
                }
            }
            req.path == "/api/pair" -> {
                val body = JSONObject(req.body)
                pairs += body
                val code = body.optString("code")
                if (codes.remove(code)) {
                    val token = "tok-${tokens.size + 1}-$code"
                    tokens += token
                    200 to """{"paired":true,"token":"$token"}"""
                } else {
                    401 to """{"paired":false,"error":"Invalid pairing code"}"""
                }
            }
            else -> 404 to "{}"
        }

        override fun close() = socket.close()
    }

    private fun pairing(configDir: File = File(tmp.root, "home/.caelza"), admin: String? = "admin-secret"): GatewayPairing {
        if (admin != null) {
            val file = File(File(configDir, GatewayPairing.DATA_DIR), GatewayPairing.ADMIN_TOKEN_FILE)
            file.parentFile.mkdirs()
            file.writeText(admin + "\n")
        }
        return GatewayPairing(configDir, File(tmp.root, "home/${GatewayPairing.TOKEN_FILE}"))
    }

    @Test
    fun theFirstStartPairsAndLaterStartsReuseTheToken() {
        FakeGateway("admin-secret").use { gw ->
            val p = pairing()
            assertNull(p.storedToken())
            val first = p.ensureToken(gw.port) as GatewayPairing.Outcome.Paired
            assertTrue(first.fresh)
            assertEquals(first.token, p.storedToken())
            assertEquals(1, gw.mints)
            assertEquals(listOf("CODE-1"), gw.pairs.map { it.getString("code") })
            assertEquals(GatewayPairing.DEVICE_NAME, gw.pairs[0].getString("device_name"))
            assertEquals(GatewayPairing.DEVICE_TYPE, gw.pairs[0].getString("device_type"))
            assertTrue(File(tmp.root, "home/${GatewayPairing.TOKEN_FILE}").readText().endsWith("\n"))

            val again = p.ensureToken(gw.port) as GatewayPairing.Outcome.Paired
            assertFalse(again.fresh)
            assertEquals(first.token, again.token)
            assertEquals("no second code", 1, gw.mints)

            // The gateway forgot the token (config reset): the app pairs again.
            synchronized(gw) { gw.tokens.clear() }
            val third = p.ensureToken(gw.port) as GatewayPairing.Outcome.Paired
            assertTrue(third.fresh)
            assertEquals(2, gw.mints)
            assertEquals(third.token, p.storedToken())
        }
    }

    @Test
    fun theWaysItCannotPairAreToldApart() {
        FakeGateway("admin-secret").use { gw ->
            val noAdmin = pairing(configDir = File(tmp.root, "other/.caelza"), admin = null)
            val failed = noAdmin.ensureToken(gw.port) as GatewayPairing.Outcome.Failed
            assertTrue(failed.detail, failed.detail.contains(GatewayPairing.ADMIN_TOKEN_FILE))

            val wrongAdmin = pairing(configDir = File(tmp.root, "wrong/.caelza"), admin = "not-it")
            val refused = wrongAdmin.ensureToken(gw.port) as GatewayPairing.Outcome.Failed
            assertTrue(refused.detail, refused.detail.contains("HTTP 401"))

            gw.pairingOn = false
            val off = pairing().ensureToken(gw.port)
            assertTrue(off.toString(), off is GatewayPairing.Outcome.Off)
        }
        val dead = pairing().ensureToken(9)
        assertTrue(dead.toString(), dead is GatewayPairing.Outcome.Failed && dead.detail.contains("does not answer"))
    }

    @Test
    fun theDashboardGetsTheTokenTheWayItsPairingScreenWould() {
        val script = GatewayPairing.tokenScript("""ab"c\d""")
        assertEquals("""try{localStorage.setItem("caelza_token","ab\"c\\d")}catch(e){}""", script)
        assertEquals("caelza_token", GatewayPairing.WEB_TOKEN_KEY)
    }
}
