package tech.enlightenedrepublic.caelza.firstrun

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import tech.enlightenedrepublic.caelza.model.ModelLadder

/** The first run's shape: the steps, what each door writes, what Cael says about this phone. */
class FirstRunTest {
    @Test
    fun the_steps_run_in_order_and_end() {
        var step: FirstRun.Step? = FirstRun.Step.HELLO
        val walked = mutableListOf<FirstRun.Step>()
        while (step != null) {
            walked += step
            step = FirstRun.next(step)
        }
        assertEquals(FirstRun.Step.values().toList(), walked)
        assertNull(FirstRun.next(FirstRun.Step.START))
    }

    @Test
    fun the_local_door_writes_what_model_setup_sh_writes() {
        val pick = ModelLadder.pick(7_600)
        assertEquals(
            listOf(
                "providers.models.llamacpp.local.model" to "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M",
                "providers.models.llamacpp.guide.model" to "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M",
                "agents.main.model_provider" to "llamacpp.local",
                "agents.cael.model_provider" to "llamacpp.guide",
                "agents.cael.risk_profile" to "guide",
                "risk_profiles.guide.level" to "readonly",
                "risk_profiles.guide.deny_all_tools" to "true",
            ),
            FirstRun.localConfig(pick),
        )
    }

    @Test
    fun the_key_door_writes_the_dotted_alias_quickstart_creates() {
        val anthropic = FirstRun.PROVIDERS.first { it.id == "anthropic" }
        val entries = FirstRun.keyConfig(anthropic, "  ", " sk-ant-abcdefghijklmnopqrstuvwxyz ")
        assertEquals("providers.models.anthropic.default.api_key" to "sk-ant-abcdefghijklmnopqrstuvwxyz", entries[0])
        assertEquals("providers.models.anthropic.default.model" to "claude-sonnet-4-5", entries[1])
        assertEquals("agents.main.model_provider" to "anthropic.default", entries[2])
        assertEquals("agents.cael.model_provider" to "anthropic.default", entries[3])
        assertTrue(entries.any { it.first == "risk_profiles.guide.deny_all_tools" && it.second == "true" })
        val openrouter = FirstRun.PROVIDERS.first { it.id == "openrouter" }
        assertEquals("providers.models.openrouter.default.model" to "google/gemini-2.5-pro", FirstRun.keyConfig(openrouter, "google/gemini-2.5-pro", "sk-or-v1-0123456789abcdef")[1])
        assertEquals(3, FirstRun.PROVIDERS.size)
        assertTrue(FirstRun.PROVIDERS.all { it.alias == "${it.id}.default" })
    }

    @Test
    fun a_key_is_one_long_word() {
        assertTrue(FirstRun.keyLooksRight("sk-ant-api03-abcdefghijklmnop"))
        assertFalse(FirstRun.keyLooksRight("short"))
        assertFalse(FirstRun.keyLooksRight("sk-ant with a space inside it here"))
        assertFalse(FirstRun.keyLooksRight("   "))
    }

    @Test
    fun cael_says_what_this_phone_gets_honestly() {
        val small = FirstRun.pickLine(ModelLadder.pick(3_500))
        assertTrue(small, small.startsWith("This phone has about 3.4 GB of RAM"))
        assertTrue(small, "one model, DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M (1065 MiB), for the agent and for me" in small)
        assertTrue(small, "bring a key later and keep me local" in small)
        val big = FirstRun.pickLine(ModelLadder.pick(8 * 1024))
        assertTrue(big, "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M (4466 MiB) for the agent and the 1.5B (1065 MiB) for me" in big)
        assertTrue(big, "tight on a phone" in big)
    }
}
