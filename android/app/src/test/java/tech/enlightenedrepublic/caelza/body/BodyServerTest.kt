package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.HttpURLConnection
import java.net.Socket
import java.net.URL
import java.util.Base64

/**
 * The Body on loopback as the Runtime's MCP client sees it: `/health` open,
 * `/mcp` behind the bearer token and the Host check, JSON-RPC over POST with
 * plain JSON answers, 202 for notifications, images as image content.
 */
class BodyServerTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val token = "t0ken-for-the-tests"
    private lateinit var shell: FakeShell
    private lateinit var server: BodyServer
    private val port: Int get() = server.port

    @Before
    fun start() {
        shell = FakeShell()
        val tools = BodyTools(BodyShell(shell), BodyHome(File(tmp.root, ".caelza-body")), FakeSensors())
        server = BodyServer(tools, token, requestedPort = 0)
        server.start()
    }

    @After
    fun stop() = server.stop()

    private fun http(method: String, path: String, body: String? = null, auth: String? = "Bearer $token"): Pair<Int, String> {
        val conn = URL("http://127.0.0.1:$port$path").openConnection() as HttpURLConnection
        conn.requestMethod = method
        conn.connectTimeout = 5_000
        conn.readTimeout = 20_000
        auth?.let { conn.setRequestProperty("Authorization", it) }
        if (body != null) {
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.setRequestProperty("Accept", "application/json, text/event-stream")
            conn.outputStream.use { it.write(body.toByteArray()) }
        }
        val code = conn.responseCode
        val stream = if (code < 400) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.readText() ?: ""
        conn.disconnect()
        return code to text
    }

    private fun rpc(method: String, params: JSONObject = JSONObject(), id: Any? = 1): JSONObject {
        val msg = JSONObject().put("jsonrpc", "2.0").put("method", method).put("params", params)
        if (id != null) msg.put("id", id)
        return msg
    }

    private fun post(msg: JSONObject): Pair<Int, JSONObject> {
        val (code, text) = http("POST", BodyServer.MCP_PATH, msg.toString())
        return code to (if (text.isEmpty()) JSONObject() else JSONObject(text))
    }

    private fun raw(request: String): String = Socket("127.0.0.1", port).use { s ->
        s.soTimeout = 5_000
        s.getOutputStream().write(request.toByteArray(Charsets.ISO_8859_1))
        s.getOutputStream().flush()
        s.getInputStream().bufferedReader(Charsets.ISO_8859_1).readText()
    }

    @Test
    fun health_answers_without_a_token_and_mcp_refuses_without_one() {
        val (code, text) = http("GET", BodyServer.HEALTH_PATH, auth = null)
        assertEquals(200, code)
        val health = JSONObject(text)
        assertTrue(health.getBoolean("ok"))
        assertEquals("caelza-body", health.getString("name"))
        assertEquals(BodyTools.SPECS.size, health.getInt("tools"))
        assertEquals("/mcp", health.getString("mcp"))
        assertEquals(401, http("POST", BodyServer.MCP_PATH, rpc("ping").toString(), auth = null).first)
        assertEquals(401, http("POST", BodyServer.MCP_PATH, rpc("ping").toString(), auth = "Bearer wrong").first)
        assertEquals(401, http("POST", BodyServer.MCP_PATH, rpc("ping").toString(), auth = "Basic $token").first)
        assertEquals(404, http("GET", "/nope", auth = null).first)
        assertEquals(405, http("GET", BodyServer.MCP_PATH).first)
    }

    @Test
    fun the_handshake_the_runtime_makes() {
        val (code, init) = post(rpc("initialize", JSONObject().put("protocolVersion", "2024-11-05").put("capabilities", JSONObject()).put("clientInfo", JSONObject().put("name", "caelza").put("version", "0"))))
        assertEquals(200, code)
        assertEquals(1, init.getInt("id"))
        val result = init.getJSONObject("result")
        assertEquals("2024-11-05", result.getString("protocolVersion"))
        assertEquals("caelza-body", result.getJSONObject("serverInfo").getString("name"))
        assertTrue(result.getJSONObject("capabilities").has("tools"))
        assertTrue("body" in result.getString("instructions"))
        // An unknown version gets the newest the server speaks.
        assertEquals("2025-06-18", post(rpc("initialize", JSONObject().put("protocolVersion", "2099-01-01"))).second.getJSONObject("result").getString("protocolVersion"))
        // The initialized notification has no id: nothing comes back but 202.
        val (notified, body) = http("POST", BodyServer.MCP_PATH, rpc("notifications/initialized", id = null).toString())
        assertEquals(202, notified)
        assertEquals("", body)
        assertEquals(JSONObject().toString(), post(rpc("ping", id = 7)).second.getJSONObject("result").toString())
    }

    @Test
    fun tools_list_carries_the_schemas_and_the_safety_hints() {
        val (code, listed) = post(rpc("tools/list", id = 2))
        assertEquals(200, code)
        val tools = listed.getJSONObject("result").getJSONArray("tools")
        assertEquals(BodyTools.SPECS.size, tools.length())
        val byName = (0 until tools.length()).map { tools.getJSONObject(it) }.associateBy { it.getString("name") }
        val uninstall = byName.getValue("device_uninstall")
        assertTrue(uninstall.getJSONObject("annotations").getBoolean("destructiveHint"))
        assertFalse(uninstall.getJSONObject("annotations").getBoolean("readOnlyHint"))
        assertEquals(listOf("pkg", "reason"), uninstall.getJSONObject("inputSchema").getJSONArray("required").let { r -> (0 until r.length()).map { r.getString(it) } })
        assertTrue(byName.getValue("device_health").getJSONObject("annotations").getBoolean("readOnlyHint"))
        assertFalse(byName.containsKey("device_pair"))
    }

    @Test
    fun tools_call_returns_text_errors_and_images_as_the_python_server_does() {
        val ok = post(rpc("tools/call", JSONObject().put("name", "device_packages").put("arguments", JSONObject().put("flags", "-3")), id = 3)).second.getJSONObject("result")
        assertFalse(ok.getBoolean("isError"))
        assertTrue(ok.getJSONArray("content").getJSONObject(0).getString("text").startsWith("exit 0\npackage:"))

        // Input validation happens server-side, before the Body runs anything.
        val bad = post(rpc("tools/call", JSONObject().put("name", "device_uninstall").put("arguments", JSONObject().put("pkg", "com.x")), id = 4)).second.getJSONObject("result")
        assertTrue(bad.getBoolean("isError"))
        val badText = bad.getJSONArray("content").getJSONObject(0).getString("text")
        assertTrue(badText, badText.contains("'reason' is a required property"))
        assertTrue(shell.calls.none { it.firstOrNull() == "pm" && "uninstall" in it })

        // The web tools are the Python Body's, not the app's: unknown here.
        val unknown = post(rpc("tools/call", JSONObject().put("name", "web_search"), id = 5)).second.getJSONObject("result")
        assertTrue(unknown.getBoolean("isError"))
        assertEquals("error: unknown tool web_search", unknown.getJSONArray("content").getJSONObject(0).getString("text"))

        val shot = post(rpc("tools/call", JSONObject().put("name", "device_screencap"), id = 6)).second.getJSONObject("result")
        assertFalse(shot.getBoolean("isError"))
        val content = shot.getJSONArray("content")
        assertEquals(listOf("text", "image", "text"), (0 until content.length()).map { content.getJSONObject(it).getString("type") })
        assertEquals("screenshot captured", content.getJSONObject(0).getString("text"))
        assertEquals("image/png", content.getJSONObject(1).getString("mimeType"))
        assertTrue(BodyTools.isPng(Base64.getDecoder().decode(content.getJSONObject(1).getString("data"))))
        assertTrue(content.getJSONObject(2).getString("text").startsWith("image saved at "))
    }

    @Test
    fun json_rpc_errors_batches_and_the_host_check() {
        val (code, err) = post(rpc("resources/list", id = 8))
        assertEquals(200, code)
        assertEquals(BodyServer.METHOD_NOT_FOUND, err.getJSONObject("error").getInt("code"))

        val (badCode, badText) = http("POST", BodyServer.MCP_PATH, "this is not json")
        assertEquals(400, badCode)
        assertEquals(BodyServer.PARSE_ERROR, JSONObject(badText).getJSONObject("error").getInt("code"))

        val batch = JSONArray().put(rpc("ping", id = 1)).put(rpc("tools/list", id = 2)).put(rpc("notifications/initialized", id = null))
        val (batchCode, batchText) = http("POST", BodyServer.MCP_PATH, batch.toString())
        assertEquals(200, batchCode)
        val answers = JSONArray(batchText)
        assertEquals(2, answers.length())
        assertEquals(listOf(1, 2), (0 until answers.length()).map { answers.getJSONObject(it).getInt("id") })

        val rebinding = raw(
            "POST /mcp HTTP/1.1\r\nHost: evil.example\r\nAuthorization: Bearer $token\r\nContent-Type: application/json\r\n" +
                "Content-Length: 2\r\nConnection: close\r\n\r\n{}",
        )
        assertTrue(rebinding, rebinding.startsWith("HTTP/1.1 421 "))
        val chunked = raw("POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nAuthorization: Bearer $token\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n")
        assertTrue(chunked, chunked.startsWith("HTTP/1.1 411 "))
    }

    @Test
    fun a_request_that_cannot_pass_is_refused_before_its_body_is_read() {
        // 16 MiB declared and none sent: the refusal comes at once, not after a wait for bytes that never come.
        val started = System.currentTimeMillis()
        val noToken = raw("POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nContent-Length: ${BodyServer.MAX_BODY}\r\n\r\n")
        assertTrue(noToken, noToken.startsWith("HTTP/1.1 401 ") && noToken.contains("Connection: close"))
        val wrongHost = raw("POST /mcp HTTP/1.1\r\nHost: evil.example\r\nAuthorization: Bearer $token\r\nContent-Length: ${BodyServer.MAX_BODY}\r\n\r\n")
        assertTrue(wrongHost, wrongHost.startsWith("HTTP/1.1 421 "))
        val wrongPath = raw("POST /nope HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nContent-Length: ${BodyServer.MAX_BODY}\r\n\r\n")
        assertTrue(wrongPath, wrongPath.startsWith("HTTP/1.1 404 "))
        assertTrue("answered within the idle timeout, so the body was never awaited", System.currentTimeMillis() - started < 10_000)
    }

    @Test
    fun connections_are_capped_and_the_one_past_the_cap_is_told_so() {
        val held = (1..BodyServer.MAX_CONNECTIONS).map { Socket("127.0.0.1", port) }
        try {
            Thread.sleep(300)
            val extra = raw("GET /health HTTP/1.1\r\nHost: 127.0.0.1:$port\r\n\r\n")
            assertTrue(extra, extra.startsWith("HTTP/1.1 503 "))
        } finally {
            held.forEach { it.close() }
        }
        Thread.sleep(300)
        assertEquals("the slots come back once those connections end", 200, http("GET", BodyServer.HEALTH_PATH, auth = null).first)
    }

    @Test
    fun one_connection_serves_several_requests() {
        val ping = rpc("ping", id = 1).toString()
        val one = "POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nAuthorization: Bearer $token\r\nContent-Type: application/json\r\nContent-Length: ${ping.length}\r\n\r\n$ping"
        val last = "POST /mcp HTTP/1.1\r\nHost: 127.0.0.1:$port\r\nAuthorization: Bearer $token\r\nContent-Type: application/json\r\nContent-Length: ${ping.length}\r\nConnection: close\r\n\r\n$ping"
        val reply = raw(one + last)
        assertEquals(2, Regex("HTTP/1.1 200 OK").findAll(reply).count())
        assertTrue(reply.contains("Connection: keep-alive") && reply.trimEnd().endsWith("}"))
    }
}
