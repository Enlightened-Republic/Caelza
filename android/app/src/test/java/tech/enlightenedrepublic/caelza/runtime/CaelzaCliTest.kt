package tech.enlightenedrepublic.caelza.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** `caelza config set` through a fake `caelza` that records what it was asked, and Cael's workspace files. */
class CaelzaCliTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private fun fakeCaelza(fail: Boolean = false): File {
        val log = File(tmp.root, "calls.log")
        val bin = File(tmp.root, "caelza")
        bin.writeText(
            "#!/bin/sh\n" +
                "printf '%s|' \"\$HOME\" >> \"${log.path}\"\n" +
                "for a in \"\$@\"; do printf '%s ' \"\$a\" >> \"${log.path}\"; done\n" +
                "printf '\\n' >> \"${log.path}\"\n" +
                (if (fail) "echo 'error: Unknown property: nope.key'; exit 2\n" else "echo ok\n"),
        )
        bin.setExecutable(true, false)
        return bin
    }

    @Test
    fun configure_runs_every_entry_in_order_with_home_set_to_the_files_dir() {
        val home = File(tmp.root, "files").apply { mkdirs() }
        val seen = mutableListOf<String>()
        CaelzaCli(fakeCaelza(), home) { seen += it }.configure(
            listOf("providers.models.llamacpp.local.model" to "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M", "agents.main.model_provider" to "llamacpp.local"),
        )
        val calls = File(tmp.root, "calls.log").readLines()
        assertEquals(
            listOf(
                "${home.path}|config set --no-interactive providers.models.llamacpp.local.model DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M ",
                "${home.path}|config set --no-interactive agents.main.model_provider llamacpp.local ",
            ),
            calls,
        )
        assertEquals(listOf("set providers.models.llamacpp.local.model", "set agents.main.model_provider"), seen)
    }

    @Test
    fun a_failing_set_stops_the_rest_and_carries_the_runtimes_message() {
        val home = File(tmp.root, "files").apply { mkdirs() }
        val cli = CaelzaCli(fakeCaelza(fail = true), home)
        val e = assertThrows(CaelzaCli.Failed::class.java) { cli.configure(listOf("nope.key" to "1", "never.reached" to "2")) }
        assertTrue(e.message, e.message!!.contains("exit 2") && e.message!!.contains("Unknown property"))
        assertEquals(1, File(tmp.root, "calls.log").readLines().size)
    }

    @Test
    fun a_caelza_that_hangs_is_killed_at_the_deadline_instead_of_holding_the_caller() {
        // Neither exits nor closes stdout: reading its output first would wait forever and the deadline would never come.
        val bin = File(tmp.root, "caelza").apply {
            writeText("#!/bin/sh\necho started\nexec sleep 60\n")
            setExecutable(true, false)
        }
        val started = System.currentTimeMillis()
        val e = assertThrows(CaelzaCli.Failed::class.java) { CaelzaCli(bin, tmp.root, timeoutMs = 1_000).configSet("a.b", "1") }
        assertTrue(e.message, e.message!!.contains("did not finish in 1s"))
        assertTrue("killed at the deadline", System.currentTimeMillis() - started < 15_000)
        val probed = System.currentTimeMillis()
        org.junit.Assert.assertNull("the installer's probe gives up the same way", ProcessProber.versionOf(bin, timeoutMs = 1_000))
        assertTrue(System.currentTimeMillis() - probed < 15_000)
    }

    @Test
    fun caels_workspace_gets_his_soul_and_identity_once() {
        val config = File(tmp.root, ".caelza")
        val ws = CaelzaCli.writeCaelPersona(config, "You are Cael.\n")
        assertEquals(File(config, "agents/cael/workspace"), ws)
        assertEquals("You are Cael.\n", File(ws, "SOUL.md").readText())
        assertTrue(File(ws, "IDENTITY.md").readText().startsWith("- **Name:** Cael\n- **Pronouns:** he/him\n"))
        File(ws, "SOUL.md").writeText("the owner's own edit\n")
        CaelzaCli.writeCaelPersona(config, "You are Cael.\n")
        assertEquals("the owner's own edit\n", File(ws, "SOUL.md").readText())
    }
}
