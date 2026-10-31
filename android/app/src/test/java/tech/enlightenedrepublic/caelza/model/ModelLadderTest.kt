package tech.enlightenedrepublic.caelza.model

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import tech.enlightenedrepublic.caelza.body.Repo
import tech.enlightenedrepublic.caelza.body.canon
import java.io.File

/** The phone ladder is `scripts/model_ladder.py`'s: the pins, the tiers by RAM, the notes, word for word. */
class ModelLadderTest {
    private val fixture: JSONObject by lazy { JSONObject(File(Repo.appFixtures, "model-ladder.json").readText()) }

    @Test
    fun the_pins_and_the_guide_tier_are_the_python_modules() {
        val export = ModelLadder.export()
        for (key in listOf("gguf", "guide_tier", "hf")) {
            assertEquals(key, canon(fixture.get(key)), canon(export.get(key)))
        }
    }

    @Test
    fun every_sample_pick_matches_the_python_pick() {
        val picks = fixture.getJSONArray("picks")
        assertTrue(picks.length() >= 5)
        for (i in 0 until picks.length()) {
            val expected = picks.getJSONObject(i)
            val ram = expected.getInt("ram_mb")
            assertEquals("ram $ram", canon(expected), canon(ModelLadder.pickJson(ModelLadder.pick(ram))))
        }
    }

    @Test
    fun six_gigabytes_is_the_line_and_cael_always_gets_the_small_one() {
        val small = ModelLadder.pick(5_000)
        assertEquals("1.5b", small.agent.tier)
        assertEquals(small.agent, small.guide)
        assertEquals(listOf(small.agent), small.files)
        assertTrue(small.notes.single().contains("not reliable for"))
        val big = ModelLadder.pick(6 * 1024)
        assertEquals("7b", big.agent.tier)
        assertEquals("1.5b", big.guide.tier)
        assertEquals(listOf(big.guide, big.agent), big.files)
        assertEquals(big.guide.bytes + big.agent.bytes, big.downloadBytes)
        assertEquals("llamacpp.local", big.providerAgent)
        assertEquals("llamacpp.guide", big.providerGuide)
        assertTrue(big.agent.url.startsWith("https://huggingface.co/bartowski/") && big.agent.url.endsWith(big.agent.file))
        assertEquals(3_500, ModelLadder.ramMb(3_500L * 1024 * 1024))
    }
}
