package tech.enlightenedrepublic.caelza.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import tech.enlightenedrepublic.caelza.body.BodyTools
import java.io.File

/** The Runtime's config names the app's Body: the http server with the token, its bundle, the agent, the phone gate. */
class BodyWiringTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun a_fresh_config_gets_the_body_server_bundle_agent_and_risk_profile_once() {
        val store = RuntimeStore(tmp.root)
        assertTrue(store.ensureBodyWiring("tok3n"))
        val text = File(store.configDir, "config.toml").readText()
        assertTrue(text.startsWith(RuntimeStore.DEFAULT_CONFIG))
        assertTrue(text.contains("[[mcp.servers]]\nname = \"body\"\ntransport = \"http\"\nurl = \"http://127.0.0.1:42618/mcp\"\nheaders = { Authorization = \"Bearer tok3n\" }\ntool_timeout_secs = 120\n"))
        assertTrue(text.contains("[mcp_bundles.body]\nservers = [\"body\"]"))
        assertTrue(text.contains("[agents.main]\nmcp_bundles = [\"body\"]\nrisk_profile = \"phone\""))
        assertTrue(text.contains("[risk_profiles.phone]\nlevel = \"supervised\""))
        val auto = text.substringAfter("auto_approve = [").substringBefore("]")
        val ask = text.substringAfter("always_ask = [").substringBefore("]")
        for (name in BodyTools.names(BodyTools.Safety.READ_ONLY)) assertTrue(name, "\"body__$name\"," in auto)
        for (name in BodyTools.names(BodyTools.Safety.DESTRUCTIVE)) assertTrue(name, "\"body__$name\"," in ask)
        assertTrue("\"body__device_uninstall\"," !in auto && "\"body__device_list\"," !in ask)
        assertFalse("\"body__device_input\"," in auto || "\"body__device_input\"," in ask)
        assertFalse("nothing to add the second time", store.ensureBodyWiring("tok3n"))
        assertEquals(text, File(store.configDir, "config.toml").readText())
        assertEquals(1, Regex("\\[agents\\.main]").findAll(text).count())
    }

    @Test
    fun a_config_the_dashboard_shaped_keeps_its_agent_and_only_gains_what_it_lacks() {
        val store = RuntimeStore(tmp.root)
        store.configDir.mkdirs()
        val own = "schema_version = 3\n\n[gateway]\nport = 42617\n\n[agents.main]\nchannels = [\"telegram.home\"]\nrisk_profile = \"phone\"\n"
        File(store.configDir, "config.toml").writeText(own)
        assertTrue(store.ensureBodyWiring("abc"))
        val text = File(store.configDir, "config.toml").readText()
        assertTrue(text.startsWith(own))
        assertEquals(1, Regex("\\[agents\\.main]").findAll(text).count())
        assertTrue("name = \"body\"" in text && "[mcp_bundles.body]" in text && "[risk_profiles.phone]" in text)
        assertEquals(42617, Gateway.port(store.configDir))
    }
}
