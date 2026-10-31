package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.time.Instant

/**
 * The device tools over the recorded phone (`FakeShell`, the Kotlin
 * `tests/fixtures/playbooks/adb.py`): the four playbook reads end to end,
 * the destructive ones' audit lines and snapshots, the one-phone guard, a
 * missing Shizuku, and the contract against the Python server's `list-tools`.
 */
class BodyToolsTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val now = Instant.parse("2026-10-24T12:00:00Z")
    private lateinit var shell: FakeShell
    private lateinit var home: BodyHome
    private lateinit var tools: BodyTools

    private fun body(fake: FakeShell = FakeShell()): BodyTools {
        shell = fake
        home = BodyHome(File(tmp.root, ".caelza-body"))
        tools = BodyTools(BodyShell(shell), home, FakeSensors()) { now }
        return tools
    }

    private fun call(name: String, vararg args: Pair<String, Any>): BodyTools.ToolResult =
        tools.call(name, JSONObject().also { o -> for ((k, v) in args) o.put(k, v) })

    private fun json(name: String, vararg args: Pair<String, Any>): JSONObject {
        val out = call(name, *args)
        assertTrue(out.text, out.text.startsWith("{"))
        return JSONObject(out.text)
    }

    private fun pkgs(arr: JSONArray): List<String> = (0 until arr.length()).map { arr.getJSONObject(it).getString("pkg") }

    private fun strings(arr: JSONArray): List<String> = (0 until arr.length()).map { arr.getString(it) }

    // --- the playbook reads over the recorded phone ------------------------------

    @Test
    fun debloat_plan_tool_runs_the_classifier_over_the_phone() {
        body()
        val plan = json("device_debloat_plan", "device" to "self")
        assertEquals("self", plan.getString("device"))
        assertEquals(301, plan.getInt("total"))
        assertEquals(6, plan.getInt("third_party"))
        assertTrue("com.metro.minus1" in pkgs(plan.getJSONArray("remove")))
        assertEquals(listOf("com.tmobile.echolocate"), strings(plan.getJSONArray("already_disabled")))
        assertEquals(listOf("com.cleaner.boost.master", "com.example.flashlightpro", "com.govee.home"), pkgs(plan.getJSONArray("review")))
        assertTrue("device_uninstall" in plan.getString("how"))
        val pinned = json("device_debloat_plan", "keep" to "com.metro.minus1, com.metropcs.metrozone")
        assertEquals(listOf("com.metro.minus1", "com.metropcs.metrozone"), strings(pinned.getJSONArray("pinned")))
        assertTrue((setOf("com.metro.minus1", "com.metropcs.metrozone") intersect pkgs(pinned.getJSONArray("remove")).toSet()).isEmpty())
    }

    @Test
    fun suspects_tool_names_the_sideloaded_apps_highest_risk_first() {
        body()
        val s = json("device_suspects")
        assertEquals(6, s.getInt("third_party"))
        assertEquals(2, s.getInt("sideloaded"))
        assertEquals(2, s.getInt("inspected"))
        assertFalse(s.getBoolean("truncated"))
        val rows = s.getJSONArray("suspects")
        assertEquals(listOf("com.example.flashlightpro", "com.cleaner.boost.master"), pkgs(rows))
        assertEquals("high", rows.getJSONObject(0).getString("risk"))
        assertEquals("low", rows.getJSONObject(1).getString("risk"))
        assertEquals(setOf("sideloaded", "overlay", "accessibility", "install_packages", "sms", "recent"), strings(rows.getJSONObject(0).getJSONArray("flags")).toSet())
        assertEquals(listOf("sideloaded"), strings(rows.getJSONObject(1).getJSONArray("flags")))
        assertEquals(listOf("com.example.flashlightpro"), strings(s.getJSONArray("accessibility_services")))
        assertEquals(0, s.getJSONArray("device_admins").length())
        assertEquals(0, s.getJSONArray("notification_listeners").length())
        assertTrue("SYSTEM_ALERT_WINDOW" in s.getString("how"))
    }

    @Test
    fun foreground_tool_identifies_the_popup_and_who_installed_it() {
        body()
        val fg = json("device_foreground")
        assertEquals("com.example.flashlightpro", fg.getString("package"))
        assertEquals("com.example.flashlightpro.ui.OfferActivity", fg.getString("activity"))
        assertEquals("com.google.android.packageinstaller", fg.getString("installer"))
        assertTrue(fg.getBoolean("sideloaded"))
        assertFalse(fg.getBoolean("system"))
        assertEquals("sideloaded: not from an app store", fg.getString("note"))
        assertTrue(strings(fg.getJSONArray("flags")).containsAll(listOf("sideloaded", "overlay", "accessibility", "sms")))
    }

    @Test
    fun health_tool_returns_the_checklist_and_attention() {
        body()
        val h = json("device_health")
        assertEquals("self", h.getString("device"))
        assertEquals("TMRV075G", h.getJSONObject("identity").getString("model"))
        assertFalse(h.getJSONObject("setup").getBoolean("termux_boot_installed"))
        assertEquals(listOf("2 crash(es) in the crash log: com.example.flashlightpro"), strings(h.getJSONArray("attention")))
    }

    @Test
    fun tools_refuse_an_unknown_device_and_report_a_missing_shizuku() {
        body()
        assertEquals("error: unknown device 'nope'", call("device_health", "device" to "nope").text)
        assertEquals("error: unknown device 'grandma'", call("device_uninstall", "pkg" to "x", "reason" to "r", "device" to "grandma").text)
        body(FakeShell(available = "not running (start it in the Shizuku app)"))
        val plan = call("device_debloat_plan")
        assertTrue(plan.text, plan.isError && "needs Shizuku" in plan.text && "start it in the Shizuku app" in plan.text)
        assertEquals("exit 127\nneeds Shizuku: not running (start it in the Shizuku app)", call("device_packages").text)
        assertFalse(json("device_list").getJSONObject("self").getBoolean("reachable"))
        val shot = call("device_screencap")
        assertTrue(shot.text, shot.isError && "needs Shizuku" in shot.text)
    }

    @Test
    fun a_script_cut_off_before_its_marker_is_an_error_not_a_shorter_answer() {
        body(object : FakeShell() {
            override fun answer(script: String): String = super.answer(script).replace("@@caelza:end", "")
        })
        val out = call("device_health")
        assertTrue(out.text, out.isError && "cut off" in out.text)
    }

    // --- the destructive ones: audit, snapshot, the pm command -------------------

    @Test
    fun uninstall_snapshots_the_package_list_audits_the_reason_then_removes() {
        body()
        val out = call("device_uninstall", "pkg" to "com.metro.minus1", "reason" to "phone-debloat: Metro feed")
        assertEquals("exit 0\nargs: pm uninstall --user 0 com.metro.minus1\n", out.text)
        val snaps = home.snapshots.listFiles()!!.toList()
        assertEquals(1, snaps.size)
        assertTrue(snaps[0].name.startsWith("self-"))
        assertTrue(snaps[0].readText().contains("package:com.metro.minus1"))
        val audit = home.auditLog.readText().trimEnd().split("\t")
        assertEquals(listOf("self", "device_uninstall", "com.metro.minus1 (snapshot ${snaps[0]})", "phone-debloat: Metro feed"), audit.drop(1))
        assertTrue(audit[0].endsWith("Z"))
        assertEquals(listOf("pm", "list", "packages", "-f"), shell.calls[0])
        assertEquals(listOf("pm", "uninstall", "--user", "0", "com.metro.minus1"), shell.calls[1])
    }

    @Test
    fun a_removal_without_a_package_list_is_aborted_and_logged_as_such() {
        body(object : FakeShell() {
            override fun answer(script: String): String = if (script.startsWith("pm list packages")) "" else super.answer(script)
        })
        val out = call("device_disable", "pkg" to "com.tmobile.echolocate", "reason" to "telemetry")
        assertTrue(out.text, out.text.startsWith("error: snapshot failed, not removing com.tmobile.echolocate"))
        assertTrue(home.auditLog.readText().contains("ABORTED: no package list"))
        assertEquals(1, shell.calls.size)
    }

    @Test
    fun settings_put_and_appops_audit_what_they_change() {
        body()
        assertEquals("exit 0\nargs: settings put global adb_enabled 1\n", call("device_settings_put", "ns" to "global", "key" to "adb_enabled", "value" to "1", "reason" to "setup").text)
        assertEquals("exit 0\nargs: appops set com.x SYSTEM_ALERT_WINDOW deny\n", call("device_appops", "pkg" to "com.x", "op" to "SYSTEM_ALERT_WINDOW", "mode" to "deny", "reason" to "overlay ads").text)
        val lines = home.auditLog.readLines()
        assertEquals(2, lines.size)
        assertTrue(lines[0].endsWith("\tself\tdevice_settings_put\tglobal adb_enabled=1\tsetup"))
        assertTrue(lines[1].endsWith("\tself\tdevice_appops\tcom.x SYSTEM_ALERT_WINDOW=deny\toverlay ads"))
    }

    @Test
    fun the_reads_run_the_same_commands_as_adb_shell_would() {
        body()
        call("device_packages", "flags" to "-f -i")
        assertEquals(listOf("pm", "list", "packages", "-f", "-i"), shell.calls.last())
        call("device_logcat", "filter" to "*:E", "lines" to 50)
        assertEquals(listOf("logcat", "-d", "-t", "50", "*:E"), shell.calls.last())
        call("device_logcat")
        assertEquals(listOf("logcat", "-d", "-t", "200"), shell.calls.last())
        call("device_settings", "ns" to "global", "key" to "adb_enabled")
        assertEquals(listOf("settings", "get", "global", "adb_enabled"), shell.calls.last())
        call("device_input", "action" to "tap", "x" to 10, "y" to 20)
        assertEquals(listOf("input", "tap", "10", "20"), shell.calls.last())
        call("device_input", "action" to "text", "text" to "hello world")
        assertEquals(listOf("input", "text", "hello world"), shell.calls.last())
        assertEquals("exit 0\nargs: uiautomator dump /sdcard/u.xml && cat /sdcard/u.xml\n", call("device_ui_dump").text)
        assertEquals("exit 0\nargs: getprop ro.product.model\n", call("device_shell", "cmd" to "getprop ro.product.model").text)
        assertEquals(listOf("sh", "-c", BodyShell.SCRIPT_PRELUDE + "getprop ro.product.model"), shell.calls.last())
        assertTrue(json("device_list").getJSONObject("self").getBoolean("reachable"))
    }

    @Test
    fun screencap_saves_the_png_under_tmp_and_hands_it_back_as_an_image() {
        body()
        val out = call("device_screencap")
        assertEquals("screenshot captured", out.text)
        assertEquals(1, out.images.size)
        val (file, mime) = out.images[0]
        assertEquals("image/png", mime)
        assertTrue(file.path, file.path.startsWith(home.tmp.path) && file.name.startsWith("screen-self-"))
        assertTrue(BodyTools.isPng(file.readBytes()))
    }

    // --- the contract: the Python server's list-tools ----------------------------

    @Test
    fun the_schemas_descriptions_and_classes_are_the_python_bodys() {
        body()
        val listed = JSONArray(File(Repo.appFixtures, "body-tools.json").readText())
        val fixture = (0 until listed.length()).map { listed.getJSONObject(it) }.associateBy { it.getString("name") }
        assertEquals(fixture.keys - BodyTools.NOT_SERVED.toSet(), tools.tools.map { it.name }.toSet())
        for (tool in tools.tools) {
            val expected = fixture.getValue(tool.name)
            assertEquals(tool.name, expected.getString("description"), tool.spec.description)
            assertEquals(tool.name, canon(expected.getJSONObject("inputSchema")), canon(JSONObject(tool.spec.schema)))
            assertEquals(tool.name, canon(expected.getJSONObject("annotations")), canon(tool.annotations()))
        }
        for (name in listOf("device_uninstall", "device_disable", "device_settings_put", "device_appops")) {
            val tool = tools.tool(name)!!
            assertEquals(BodyTools.Safety.DESTRUCTIVE, tool.spec.safety)
            assertTrue(name, "reason" in (0 until JSONObject(tool.spec.schema).getJSONArray("required").length()).map { JSONObject(tool.spec.schema).getJSONArray("required").getString(it) })
        }
        for (name in listOf("device_debloat_plan", "device_suspects", "device_foreground", "device_health")) {
            assertEquals(BodyTools.Safety.READ_ONLY, tools.tool(name)!!.spec.safety)
        }
    }

    @Test
    fun arguments_are_validated_before_anything_runs() {
        body()
        assertEquals("error: input validation: 'reason' is a required property", call("device_uninstall", "pkg" to "com.x").text)
        assertTrue(call("device_input", "action" to "jump").text.startsWith("error: input validation: action:"))
        assertTrue(call("device_logcat", "lines" to "many").text.startsWith("error: input validation: lines:"))
        assertEquals("error: unknown tool device_fly", call("device_fly").text)
        assertEquals(0, shell.calls.size)
        // A missing coordinate reaches `input` as the word None, as the Python Body sends it; the phone's `input` answers.
        call("device_input", "action" to "swipe", "x" to 1)
        assertEquals(listOf("input", "swipe", "1", "None", "None", "None"), shell.calls.last())
        assertNull(BodyTools.validate(JSONObject("""{"type":"object","properties":{"n":{"type":"integer"}}}"""), JSONObject().put("n", 3)))
        assertEquals(listOf("-f", "-i", "a b"), BodyTools.shlexSplit("-f -i 'a b'"))
        assertEquals("com.x", BodyTools.shellQuote("com.x"))
        assertEquals("'a b'", BodyTools.shellQuote("a b"))
    }
}
