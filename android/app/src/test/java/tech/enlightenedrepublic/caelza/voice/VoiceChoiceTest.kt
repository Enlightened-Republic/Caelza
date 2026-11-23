package tech.enlightenedrepublic.caelza.voice

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/** The agent's saved voice as the Body reads it, and which agent's voice that is. */
class VoiceChoiceTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun a_saved_choice_parses_and_the_numbers_are_bounded() {
        val c = VoiceChoice.parse(
            """{"version":1,"engine":"phone","voice":"en-gb-x-gba-local","name":"en-GB · en-gb-x-gba-local","rate":1.2,"pitch":0.9,"why":"it suits me"}""",
        )!!
        assertEquals("phone", c.engine)
        assertEquals("en-gb-x-gba-local", c.voice)
        assertEquals("en-GB · en-gb-x-gba-local", c.name)
        assertEquals(1.2f, c.rate, 0.0001f)
        assertEquals(0.9f, c.pitch, 0.0001f)
        val bare = VoiceChoice.parse("""{"engine":"elevenlabs","voice":"21m00Tcm4TlvDq8ikWAM"}""")!!
        assertNull(bare.name)
        assertEquals(1f, bare.rate, 0f)
        assertEquals(1f, bare.pitch, 0f)
        assertEquals(VoiceChoice.MAX, VoiceChoice.parse("""{"engine":"phone","voice":"x","rate":9}""")!!.rate, 0f)
        assertEquals(VoiceChoice.MIN, VoiceChoice.parse("""{"engine":"phone","voice":"x","pitch":0.1}""")!!.pitch, 0f)
        assertEquals(1f, VoiceChoice.parse("""{"engine":"phone","voice":"x","rate":"fast"}""")!!.rate, 0f)
    }

    @Test
    fun what_is_not_a_choice_is_null() {
        for (bad in listOf("", "nope", "[]", """{"engine":"radio","voice":"x"}""", """{"engine":"phone"}""", """{"voice":"x"}""", """{"engine":"phone","voice":"  "}""")) {
            assertNull(bad, VoiceChoice.parse(bad))
        }
    }

    @Test
    fun the_choice_is_read_from_the_agents_folder_and_missing_means_none() {
        val dir = tmp.newFolder(".caelza")
        assertNull(VoiceChoice.read(dir, "main"))
        VoiceChoice.file(dir, "main").apply {
            parentFile!!.mkdirs()
            writeText("""{"engine":"phone","voice":"en-us-x-iom-local"}""")
        }
        assertEquals("en-us-x-iom-local", VoiceChoice.read(dir, "main")?.voice)
        assertNull(VoiceChoice.read(dir, "cael"))
        VoiceChoice.file(dir, "main").writeText("not json")
        assertNull(VoiceChoice.read(dir, "main"))
    }

    @Test
    fun the_body_agent_is_the_one_carrying_the_body_and_main_wins() {
        assertEquals("main", VoiceChoice.bodyAgent(""))
        assertEquals("main", VoiceChoice.bodyAgent("[agents.main]\nmodel_provider = \"x\"\n"))
        assertEquals("moss", VoiceChoice.bodyAgent("[agents.cael]\nrisk_profile = \"guide\"\n\n[agents.moss]\nmcp_bundles = [\"body\"]\nrisk_profile = \"phone\"\n"))
        assertEquals("main", VoiceChoice.bodyAgent("[agents.moss]\nmcp_bundles = [\"body\"]\n\n[agents.main]\nmcp_bundles = [\"body\", \"other\"]\n"))
        // The bundle's own table and another agent's other bundles are not carriers.
        assertEquals("main", VoiceChoice.bodyAgent("[mcp_bundles.body]\nservers = [\"body\"]\n\n[agents.cael]\nmcp_bundles = [\"notes\"]\n"))
    }
}
