package tech.enlightenedrepublic.caelza.body

import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.ConnectException

/** The Body's way to the agent's voice: whose choice it reads, and the gateway's ElevenLabs route behind the app's token. */
class BodyVoiceTest {
    @get:Rule
    val tmp = TemporaryFolder()

    /** A fresh Runtime config dir (one test makes several). */
    private fun configDir(vararg files: Pair<String, String>): File {
        val dir = File(tmp.newFolder(), ".caelza").apply { mkdirs() }
        for ((path, text) in files) File(dir, path).apply {
            parentFile!!.mkdirs()
            writeText(text)
        }
        return dir
    }

    @Test
    fun the_choice_is_the_body_agents_and_none_without_files() {
        assertNull(BodyVoice.NONE.choice())
        assertEquals("main", BodyVoice.NONE.alias())
        val dir = configDir(
            "config.toml" to "[agents.moss]\nmcp_bundles = [\"body\"]\n",
            "agents/moss/voice.json" to """{"engine":"phone","voice":"en-gb-x-gba-local"}""",
            "agents/main/voice.json" to """{"engine":"phone","voice":"other"}""",
        )
        val voice = BodyVoice(dir)
        assertEquals("moss", voice.alias())
        assertEquals("en-gb-x-gba-local", voice.choice()?.voice)
        assertEquals("main", BodyVoice(configDir()).alias())
    }

    @Test
    fun elevenlabs_goes_through_the_gateway_with_the_apps_token() {
        val seen = mutableListOf<String>()
        val fetch = BodyVoice.Fetch { url, token, json ->
            seen += "$url $token $json"
            BodyVoice.Reply(200, byteArrayOf(0x49, 0x44, 0x33))
        }
        val voice = BodyVoice(configDir(), port = { 42617 }, token = { "tok-1" }, fetch = fetch)
        val mp3 = voice.elevenLabs("main", "Hello there").getOrThrow()
        assertArrayEquals(byteArrayOf(0x49, 0x44, 0x33), mp3)
        assertEquals(listOf("""http://127.0.0.1:42617/api/voice/main/speak tok-1 {"text":"Hello there"}"""), seen)
    }

    @Test
    fun what_stops_the_gateway_speaking_is_a_reason_not_a_crash() {
        val notReached = BodyVoice.Fetch { _, _, _ -> throw AssertionError("not reached") }
        val noToken = BodyVoice(configDir(), token = { null }, fetch = notReached)
        assertEquals("the app is not paired with the gateway", noToken.elevenLabs("main", "hi").exceptionOrNull()?.message)
        val refused = BodyVoice(configDir(), token = { "t" }, fetch = { _, _, _ ->
            BodyVoice.Reply(404, """{"error":"no ElevenLabs key yet; add one on the Connect page"}""".toByteArray())
        })
        assertEquals("the gateway answered HTTP 404: no ElevenLabs key yet; add one on the Connect page", refused.elevenLabs("main", "hi").exceptionOrNull()?.message)
        val down = BodyVoice(configDir(), token = { "t" }, fetch = { _, _, _ -> throw ConnectException("Connection refused") })
        assertEquals("the gateway did not answer: Connection refused", down.elevenLabs("main", "hi").exceptionOrNull()?.message)
        val silent = BodyVoice(configDir(), token = { "t" }, fetch = { _, _, _ -> BodyVoice.Reply(200, ByteArray(0)) })
        assertEquals("the gateway sent no audio", silent.elevenLabs("main", "hi").exceptionOrNull()?.message)
        val long = BodyVoice(configDir(), token = { "t" }, fetch = notReached)
        assertTrue(long.elevenLabs("main", "x".repeat(BodyVoice.MAX_SPEAK_CHARS + 1)).exceptionOrNull()!!.message!!.contains("2000"))
        // A reason never carries the token.
        val leak = BodyVoice(configDir(), token = { "secret-token" }, fetch = { _, _, _ -> BodyVoice.Reply(500, "boom".toByteArray()) })
        val reason = leak.elevenLabs("main", "hi").exceptionOrNull()!!.message!!
        assertEquals("the gateway answered HTTP 500", reason)
        assertFalse(reason.contains("secret"))
    }
}
