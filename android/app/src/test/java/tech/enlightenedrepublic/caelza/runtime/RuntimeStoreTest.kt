package tech.enlightenedrepublic.caelza.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

class RuntimeStoreTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private fun store() = RuntimeStore(File(tmp.root, "home"))

    private fun install(store: RuntimeStore, version: String, marker: String = "") {
        val dir = store.versionDir(version)
        dir.mkdirs()
        File(dir, "caelza").writeText("#!/bin/sh\n# $version $marker\n")
    }

    @Test
    fun pointers_promote_switch_rollback() {
        val s = store()
        assertNull(s.current)
        assertNull(s.currentBinary)
        assertEquals(emptyList<String>(), s.installed())
        for (v in listOf("0.1.0", "0.1.1", "0.1.2")) install(s, v)
        s.promote("0.1.0")
        assertEquals("0.1.0", s.current)
        assertEquals("0.1.0", s.lastGood)
        assertEquals(s.binary("0.1.0"), s.currentBinary)
        s.switch("0.1.1")
        assertEquals("0.1.1", s.current)
        assertEquals("0.1.0", s.lastGood)
        assertEquals("0.1.0", s.rollback())
        assertEquals("0.1.0", s.current)
        assertNull("already on last-good", s.rollback())
        // A last-good whose binary is gone is nothing to fall back to, not an exception.
        s.switch("0.1.2")
        s.versionDir("0.1.0").deleteRecursively()
        assertEquals("0.1.0", s.lastGood)
        assertNull(s.rollback())
        assertEquals("0.1.2", s.current)
        // A dangling current has no binary.
        s.versionDir("0.1.2").deleteRecursively()
        assertEquals("0.1.2", s.current)
        assertNull(s.currentBinary)
    }

    @Test
    fun versions_sort_numerically_and_prune_pins_what_still_runs() {
        val s = store()
        for (v in listOf("0.8.0", "0.9.0", "0.10.0", "0.11.0")) install(s, v)
        assertEquals(listOf("0.8.0", "0.9.0", "0.10.0", "0.11.0"), s.installed())
        s.promote("0.9.0")
        s.switch("0.11.0")
        assertEquals(listOf("0.8.0"), s.prune(keep = 2, pin = setOf("0.10.0")))
        assertEquals(listOf("0.9.0", "0.10.0", "0.11.0"), s.installed())
        assertEquals(
            listOf("0.1.0", "0.9.0", "0.10.0", "1.0.0-rc1"),
            listOf("0.10.0", "0.9.0", "0.1.0", "1.0.0-rc1").sortedWith(RuntimeStore.VERSION_ORDER),
        )
    }

    @Test
    fun install_version_swaps_a_previous_copy_whole_and_marks_the_binary_executable() {
        val s = store()
        install(s, "0.1.0", "first")
        s.promote("0.1.0")
        File(s.versionDir("0.1.0"), "stale").writeText("old")
        val extracted = File(tmp.root, "x/caelza-0.1.0-aarch64-linux-android").apply { mkdirs() }
        File(extracted, "caelza").writeText("#!/bin/sh\n# second\n")
        s.installVersion("0.1.0", extracted)
        assertTrue(s.binary("0.1.0").canExecute())
        assertTrue(s.binary("0.1.0").readText().contains("second"))
        assertFalse(File(s.versionDir("0.1.0"), "stale").exists())
        assertFalse(File(s.root, "0.1.0.old").exists())
        assertFalse(extracted.exists())
    }

    @Test
    fun ensure_config_writes_a_loopback_gateway_once_and_the_web_dist_goes_where_the_gateway_looks() {
        val s = store()
        val config = s.ensureConfig()
        assertTrue(config.readText().contains("require_pairing = true"))
        assertEquals(RuntimeStore.GATEWAY_PORT, Gateway.port(s.configDir))
        config.writeText("schema_version = 3\n\n[gateway]\nport = 4242\n")
        s.ensureConfig()
        assertEquals(4242, Gateway.port(s.configDir))
        // A config this app wrote before it could pair itself (M7a: pairing off) is turned on, nothing else touched.
        config.writeText("schema_version = 3\n\n[gateway]\nhost = \"127.0.0.1\"\nport = 4242\n  require_pairing = false\n\n[agents.main]\nrisk_profile = \"phone\"\n")
        s.ensureConfig()
        assertEquals("schema_version = 3\n\n[gateway]\nhost = \"127.0.0.1\"\nport = 4242\n  require_pairing = true\n\n[agents.main]\nrisk_profile = \"phone\"\n", config.readText())
        s.ensureConfig()
        assertTrue(config.readText().contains("  require_pairing = true\n"))
        val dist = File(tmp.root, "dist").apply { mkdirs() }
        File(dist, "index.html").writeText("<html>caelza</html>")
        s.installWebDist(dist)
        assertEquals("<html>caelza</html>", File(s.webDist, "index.html").readText())
    }
}
