package tech.enlightenedrepublic.caelza.body

import org.json.JSONObject
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import tech.enlightenedrepublic.caelza.voice.VoiceChoice
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * The Body speaking in the agent's own voice (vision M10 §10, slice P2c). The
 * choice is `agents/<alias>/voice.json` under the Runtime's config dir, saved
 * by the agent's `voice` tool or the Looks page; the alias is the agent that
 * carries the Body ([VoiceChoice.bodyAgent]). A phone voice the engine speaks
 * itself ([Sensors.ttsSpeak] with its name, speed and pitch); an ElevenLabs
 * voice is fetched as MP3 from the gateway's `POST /api/voice/<alias>/speak`
 * with the app's own paired token and played ([Sensors.play]); a browser voice
 * is the PC's, so the phone speaks in its own. The gateway not speaking never
 * fails the tool: the phone speaks instead and the answer says why. The token
 * goes in a header and nowhere else: not in an answer, not in a log.
 */
class BodyVoice(
    private val configDir: File?,
    private val port: () -> Int = { RuntimeStore.GATEWAY_PORT },
    /** The app's paired bearer token; "" when the gateway needs none; null when there is none to be had. */
    private val token: () -> String? = { null },
    private val fetch: Fetch = HttpFetch,
) {
    /** `POST url` with a bearer token (none when blank) and a JSON body: the status and the bytes (an error's text as bytes). */
    fun interface Fetch {
        fun post(url: String, token: String, json: String): Reply
    }

    class Reply(val code: Int, val bytes: ByteArray)

    /** The agent whose voice the Body speaks in. */
    fun alias(): String {
        val config = configDir?.let { File(it, "config.toml") } ?: return "main"
        val text = try {
            config.takeIf { it.isFile }?.readText()
        } catch (_: Exception) {
            null
        } ?: return "main"
        return VoiceChoice.bodyAgent(text)
    }

    fun choice(): VoiceChoice? = configDir?.let { VoiceChoice.read(it, alias()) }

    /** `text` as MP3 in the agent's ElevenLabs voice, or why the phone speaks instead (one line, never the token). */
    fun elevenLabs(alias: String, text: String): Result<ByteArray> {
        if (text.length > MAX_SPEAK_CHARS) {
            return Result.failure(IllegalArgumentException("the text is longer than $MAX_SPEAK_CHARS characters"))
        }
        val bearer = try {
            token()
        } catch (_: Exception) {
            null
        } ?: return Result.failure(IllegalStateException("the app is not paired with the gateway"))
        val url = "http://127.0.0.1:${port()}/api/voice/$alias/speak"
        val reply = try {
            fetch.post(url, bearer, JSONObject().put("text", text).toString())
        } catch (e: Exception) {
            return Result.failure(IllegalStateException("the gateway did not answer: ${e.message ?: e.javaClass.simpleName}"))
        }
        if (reply.code !in 200..299) {
            val message = try {
                JSONObject(String(reply.bytes, Charsets.UTF_8)).optString("error", "")
            } catch (_: Exception) {
                ""
            }
            return Result.failure(IllegalStateException("the gateway answered HTTP ${reply.code}" + if (message.isNotEmpty()) ": $message" else ""))
        }
        if (reply.bytes.isEmpty()) return Result.failure(IllegalStateException("the gateway sent no audio"))
        return Result.success(reply.bytes)
    }

    companion object {
        /** `api_voice.rs` MAX_SPEAK_CHARS: the gateway refuses longer texts, so the phone speaks them. */
        const val MAX_SPEAK_CHARS = 2000

        /** No Runtime files at hand (the tests): the phone's own voice, always. */
        val NONE = BodyVoice(null)

        object HttpFetch : Fetch {
            override fun post(url: String, token: String, json: String): Reply {
                val conn = URL(url).openConnection() as HttpURLConnection
                try {
                    conn.connectTimeout = 5_000
                    conn.readTimeout = 60_000
                    conn.requestMethod = "POST"
                    if (token.isNotBlank()) conn.setRequestProperty("Authorization", "Bearer $token")
                    conn.setRequestProperty("Content-Type", "application/json")
                    conn.setRequestProperty("Accept", "audio/mpeg")
                    conn.doOutput = true
                    conn.outputStream.use { it.write(json.toByteArray(Charsets.UTF_8)) }
                    val code = conn.responseCode
                    val stream = if (code in 200..299) conn.inputStream else conn.errorStream
                    val bytes = stream?.use { it.readBytes() } ?: ByteArray(0)
                    return Reply(code, bytes)
                } finally {
                    conn.disconnect()
                }
            }
        }
    }
}
