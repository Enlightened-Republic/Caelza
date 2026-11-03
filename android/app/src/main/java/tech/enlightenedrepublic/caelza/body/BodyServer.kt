package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import org.json.JSONTokener
import java.io.BufferedInputStream
import java.io.BufferedOutputStream
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.InetSocketAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketTimeoutException
import java.security.MessageDigest
import java.util.Base64
import java.util.concurrent.Semaphore
import java.util.concurrent.atomic.AtomicBoolean

/**
 * The Body as an MCP server on loopback, the way `caelza-body serve --http`
 * serves it (`caelza_body/fleet.py`): Streamable HTTP at `/mcp` behind a
 * bearer token, `/health` open (name, version, tool count) so reachability
 * and a bad token read differently, the Host header checked against
 * loopback. Requests are JSON-RPC 2.0 POSTs answered with plain JSON (the
 * Runtime's client accepts JSON or an event stream, and sends no session);
 * notifications get 202. `initialize`, `ping`, `tools/list` and `tools/call`
 * are the surface, as the Python server's. One small HTTP/1.1 reader rather
 * than a web framework: the app ships no server dependency and the tests run
 * it on the JVM.
 */
class BodyServer(
    private val tools: BodyTools,
    private val token: String,
    val requestedPort: Int = PORT,
    private val host: String = "127.0.0.1",
    private val log: (String) -> Unit = {},
) {
    private var socket: ServerSocket? = null
    private val running = AtomicBoolean(false)
    /** Connections being served: past the cap the next one is told 503 and closed, so no app on the phone can pile up threads. */
    private val connections = Semaphore(MAX_CONNECTIONS)

    val port: Int get() = socket?.localPort ?: requestedPort
    val isRunning: Boolean get() = running.get()

    /** Bind and start answering; a port something else holds raises `BindException`. */
    fun start() {
        if (running.get()) return
        val ss = ServerSocket()
        ss.reuseAddress = true
        ss.bind(InetSocketAddress(host, requestedPort), 16)
        socket = ss
        running.set(true)
        Thread({ acceptLoop(ss) }, "caelza-body-http").apply {
            isDaemon = true
            start()
        }
    }

    fun stop() {
        running.set(false)
        try {
            socket?.close()
        } catch (_: Exception) {
        }
        socket = null
    }

    private fun acceptLoop(ss: ServerSocket) {
        while (running.get()) {
            val client = try {
                ss.accept()
            } catch (_: Exception) {
                if (running.get()) continue else break
            }
            if (!connections.tryAcquire()) {
                Thread({ refuseBusy(client) }, "caelza-body-busy").apply {
                    isDaemon = true
                    start()
                }
                continue
            }
            Thread({
                try {
                    serve(client)
                } finally {
                    connections.release()
                }
            }, "caelza-body-conn").apply {
                isDaemon = true
                start()
            }
        }
    }

    private fun refuseBusy(client: Socket) {
        try {
            client.use { sock ->
                sock.soTimeout = 2_000
                writeResponse(BufferedOutputStream(sock.getOutputStream()), Response(503, TEXT, "too many connections".toByteArray()), close = true)
            }
        } catch (_: Exception) {
        }
    }

    private fun serve(client: Socket) {
        client.use { sock ->
            sock.soTimeout = IDLE_TIMEOUT_MS
            val input = BufferedInputStream(sock.getInputStream())
            val output = BufferedOutputStream(sock.getOutputStream())
            while (running.get()) {
                // The head first; a request that cannot pass is refused before a byte of its
                // body is read, so a stranger on the phone cannot make the Body hold 16 MiB
                // per connection while it waits for bytes that never come.
                val request = try {
                    val head = readHead(input) ?: return
                    refusal(head)?.let { r ->
                        writeResponse(output, r, close = true)
                        return
                    }
                    Request(head.method, head.path, head.headers, readBody(input, head.length))
                } catch (e: HttpError) {
                    writeResponse(output, Response(e.status, TEXT, (e.message ?: "bad request").toByteArray()), close = true)
                    return
                } catch (_: SocketTimeoutException) {
                    return
                } catch (_: IOException) {
                    return
                }
                val response = try {
                    handle(request)
                } catch (e: Exception) {
                    log("request failed: $e")
                    Response(500, TEXT, "internal error".toByteArray())
                }
                val close = request.header("connection").equals("close", ignoreCase = true)
                try {
                    writeResponse(output, response, close)
                } catch (_: IOException) {
                    return
                }
                if (close) return
            }
        }
    }

    // --- HTTP -----------------------------------------------------------------

    /** The request line and the headers, before the body is read. */
    private class Head(val method: String, val path: String, val headers: Map<String, String>, val length: Long) {
        fun header(name: String): String? = headers[name.lowercase()]
    }

    private class Request(val method: String, val path: String, val headers: Map<String, String>, val body: ByteArray) {
        fun header(name: String): String? = headers[name.lowercase()]
    }

    private class Response(val status: Int, val contentType: String, val body: ByteArray, val allow: String? = null)

    private class HttpError(val status: Int, message: String) : IOException(message)

    private fun readLine(input: InputStream, limit: Int = 8192): String? {
        val buf = ByteArrayOutputStream()
        while (true) {
            val b = input.read()
            if (b == -1) return if (buf.size() == 0) null else buf.toString("ISO-8859-1")
            if (b == '\n'.code) break
            if (buf.size() >= limit) throw HttpError(431, "header line too long")
            buf.write(b)
        }
        return buf.toString("ISO-8859-1").trimEnd('\r')
    }

    /** The request line and the headers, or null at a clean end of the connection. */
    private fun readHead(input: InputStream): Head? {
        var line = readLine(input) ?: return null
        while (line.isEmpty()) line = readLine(input) ?: return null
        val parts = line.split(' ')
        if (parts.size < 2) throw HttpError(400, "bad request line")
        val headers = HashMap<String, String>()
        var count = 0
        while (true) {
            val h = readLine(input) ?: throw HttpError(400, "unexpected end of headers")
            if (h.isEmpty()) break
            if (++count > 100) throw HttpError(431, "too many headers")
            val colon = h.indexOf(':')
            if (colon <= 0) continue
            headers[h.substring(0, colon).trim().lowercase()] = h.substring(colon + 1).trim()
        }
        if (headers["transfer-encoding"]?.contains("chunked", ignoreCase = true) == true) {
            throw HttpError(411, "chunked bodies are not accepted; send Content-Length")
        }
        val length = headers["content-length"]?.toLongOrNull() ?: 0L
        if (length < 0 || length > MAX_BODY) throw HttpError(413, "body too large")
        return Head(parts[0], parts[1], headers, length)
    }

    /**
     * What a request fails on before its body is worth reading: the path, then for `/mcp` the
     * Host and the bearer, then the method. Null means read the body and handle it.
     */
    private fun refusal(head: Head): Response? {
        val path = head.path.substringBefore('?')
        if (path == HEALTH_PATH) {
            if (head.method != "GET") return Response(405, TEXT, "method not allowed".toByteArray(), allow = "GET")
            if (head.length > 0) return Response(400, TEXT, "no body expected".toByteArray())
            return null
        }
        if (path != MCP_PATH) return Response(404, TEXT, "not found".toByteArray())
        if (!hostOk(head.header("host"))) return Response(421, TEXT, "unexpected Host header".toByteArray())
        if (!bearerOk(head.header("authorization"))) return Response(401, TEXT, "unauthorized".toByteArray())
        if (head.method != "POST") return Response(405, TEXT, "method not allowed".toByteArray(), allow = "POST")
        return null
    }

    /** The body of a request that passed, read in pieces rather than allocated whole up front. */
    private fun readBody(input: InputStream, length: Long): ByteArray {
        if (length == 0L) return ByteArray(0)
        val out = ByteArrayOutputStream(minOf(length, 64L * 1024).toInt())
        val buf = ByteArray(16 * 1024)
        var remaining = length
        while (remaining > 0) {
            val n = input.read(buf, 0, minOf(buf.size.toLong(), remaining).toInt())
            if (n < 0) throw HttpError(400, "body cut short")
            out.write(buf, 0, n)
            remaining -= n
        }
        return out.toByteArray()
    }

    private fun writeResponse(out: OutputStream, r: Response, close: Boolean) {
        val head = StringBuilder()
            .append("HTTP/1.1 ").append(r.status).append(' ').append(REASONS[r.status] ?: "Unknown").append("\r\n")
            .append("Content-Type: ").append(r.contentType).append("\r\n")
            .append("Content-Length: ").append(r.body.size).append("\r\n")
        r.allow?.let { head.append("Allow: ").append(it).append("\r\n") }
        head.append("Connection: ").append(if (close) "close" else "keep-alive").append("\r\n\r\n")
        out.write(head.toString().toByteArray(Charsets.ISO_8859_1))
        out.write(r.body)
        out.flush()
    }

    private fun handle(request: Request): Response {
        val path = request.path.substringBefore('?')
        if (path == HEALTH_PATH) {
            if (request.method != "GET") return Response(405, TEXT, "method not allowed".toByteArray(), allow = "GET")
            return json(200, health())
        }
        if (path != MCP_PATH) return Response(404, TEXT, "not found".toByteArray())
        if (!hostOk(request.header("host"))) return Response(421, TEXT, "unexpected Host header".toByteArray())
        if (!bearerOk(request.header("authorization"))) return Response(401, TEXT, "unauthorized".toByteArray())
        return when (request.method) {
            "POST" -> post(request)
            else -> Response(405, TEXT, "method not allowed".toByteArray(), allow = "POST")
        }
    }

    fun health(): JSONObject = JSONObject().put("ok", true).put("name", SERVER_NAME).put("tools", tools.tools.size).put("mcp", MCP_PATH)

    /** DNS-rebinding protection: only the loopback names reach `/mcp` (`fleet.allowed_hosts_for`). */
    private fun hostOk(header: String?): Boolean {
        val h = header?.trim()?.lowercase() ?: return false
        val p = port
        return h in setOf(host, "$host:$p", "127.0.0.1", "127.0.0.1:$p", "localhost", "localhost:$p", "[::1]", "[::1]:$p")
    }

    /** `Authorization: Bearer <token>` against the token, in constant time (`fleet.bearer_ok`). */
    private fun bearerOk(header: String?): Boolean {
        if (header == null || !header.startsWith("Bearer ")) return false
        val candidate = header.removePrefix("Bearer ").trim()
        if (candidate.isEmpty() || candidate.any { it.code > 127 }) return false
        return MessageDigest.isEqual(candidate.toByteArray(Charsets.US_ASCII), token.toByteArray(Charsets.US_ASCII))
    }

    private fun json(status: Int, body: Any): Response = Response(status, JSON, body.toString().toByteArray(Charsets.UTF_8))

    // --- JSON-RPC / MCP ----------------------------------------------------------

    private fun post(request: Request): Response {
        val text = String(request.body, Charsets.UTF_8)
        val parsed: Any? = try {
            JSONTokener(text).nextValue()
        } catch (e: JSONException) {
            return json(400, rpcError(JSONObject.NULL, PARSE_ERROR, "parse error: ${e.message}"))
        }
        val messages: List<Any?> = when (parsed) {
            is JSONArray -> (0 until parsed.length()).map { parsed.get(it) }
            is JSONObject -> listOf(parsed)
            else -> return json(400, rpcError(JSONObject.NULL, PARSE_ERROR, "parse error: not a JSON-RPC message"))
        }
        if (messages.isEmpty() || messages.any { it !is JSONObject }) {
            return json(400, rpcError(JSONObject.NULL, INVALID_REQUEST, "invalid request"))
        }
        val responses = messages.mapNotNull { dispatch(it as JSONObject) }
        if (responses.isEmpty()) return Response(202, TEXT, ByteArray(0))
        return json(200, if (parsed is JSONArray) JSONArray(responses) else responses[0])
    }

    /** One JSON-RPC message; null for a notification or a stray response (nothing goes back). */
    private fun dispatch(msg: JSONObject): JSONObject? {
        if (!msg.has("method")) return null
        val method = msg.optString("method", "")
        val hasId = msg.has("id") && !msg.isNull("id")
        if (!hasId) return null
        val id = msg.get("id")
        if (method.isEmpty()) return rpcError(id, INVALID_REQUEST, "invalid request: no method")
        val params = msg.optJSONObject("params") ?: JSONObject()
        return when (method) {
            "initialize" -> rpcResult(id, initialize(params))
            "ping" -> rpcResult(id, JSONObject())
            "tools/list" -> rpcResult(id, JSONObject().put("tools", JSONArray(tools.tools.map { it.mcp() })))
            "tools/call" -> rpcResult(id, callTool(params))
            else -> rpcError(id, METHOD_NOT_FOUND, "Method not found: $method")
        }
    }

    private fun initialize(params: JSONObject): JSONObject {
        val requested = params.optString("protocolVersion", "")
        val version = if (requested in PROTOCOL_VERSIONS) requested else PROTOCOL_VERSIONS.first()
        return JSONObject()
            .put("protocolVersion", version)
            .put("capabilities", JSONObject().put("tools", JSONObject().put("listChanged", false)))
            .put("serverInfo", JSONObject().put("name", SERVER_NAME).put("version", SERVER_VERSION))
            .put("instructions", INSTRUCTIONS)
    }

    /** `tools/call` → the text, then each image as image content plus the line saying where it was saved (`mcp_server.call_tool`). */
    private fun callTool(params: JSONObject): JSONObject {
        val result = tools.call(params.optString("name", ""), params.optJSONObject("arguments"))
        val content = JSONArray().put(textBlock(result.text))
        for ((file, mime) in result.images) {
            val bytes = try {
                file.readBytes()
            } catch (e: IOException) {
                content.put(textBlock("image at ${file.path} could not be read: ${e.message}"))
                continue
            }
            content.put(JSONObject().put("type", "image").put("data", Base64.getEncoder().encodeToString(bytes)).put("mimeType", mime))
            content.put(textBlock("image saved at ${file.path} ($mime, ${bytes.size} bytes)"))
        }
        return JSONObject().put("content", content).put("isError", result.isError)
    }

    private fun textBlock(text: String): JSONObject = JSONObject().put("type", "text").put("text", text)

    private fun rpcResult(id: Any, result: JSONObject): JSONObject = JSONObject().put("jsonrpc", "2.0").put("id", id).put("result", result)

    private fun rpcError(id: Any, code: Int, message: String): JSONObject =
        JSONObject().put("jsonrpc", "2.0").put("id", id).put("error", JSONObject().put("code", code).put("message", message))

    companion object {
        /** `fleet.DEFAULT_PORT`, `fleet.MCP_PATH`, `fleet.HEALTH_PATH`. */
        const val PORT = 42618
        const val MCP_PATH = "/mcp"
        const val HEALTH_PATH = "/health"
        const val SERVER_NAME = "caelza-body"
        const val SERVER_VERSION = "0.1.0"
        const val INSTRUCTIONS =
            "This server is the agent's body: the phone it runs on, reached through Shizuku. 'self' always means this phone. " +
                "Tools marked DANGEROUS change device state; they need a `reason`, which is written to the Body's audit log, " +
                "and removals snapshot the package list first. Screenshots come back as image content and are also saved " +
                "under the Body's tmp dir, whose path is in the text result."

        /** Newest first: an unknown request gets the first; a known one is echoed. */
        val PROTOCOL_VERSIONS = listOf("2025-06-18", "2025-03-26", "2024-11-05")

        const val PARSE_ERROR = -32700
        const val INVALID_REQUEST = -32600
        const val METHOD_NOT_FOUND = -32601

        const val IDLE_TIMEOUT_MS = 60_000
        const val MAX_BODY = 16L * 1024 * 1024
        /** The Runtime's MCP client holds one or two; the rest is headroom, not a pool for strangers. */
        const val MAX_CONNECTIONS = 8

        private const val TEXT = "text/plain; charset=utf-8"
        private const val JSON = "application/json"

        private val REASONS = mapOf(
            200 to "OK", 202 to "Accepted", 400 to "Bad Request", 401 to "Unauthorized", 404 to "Not Found",
            405 to "Method Not Allowed", 411 to "Length Required", 413 to "Payload Too Large", 421 to "Misdirected Request",
            431 to "Request Header Fields Too Large", 500 to "Internal Server Error", 503 to "Service Unavailable",
        )
    }
}
