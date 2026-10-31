package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.Instant

/**
 * `tests/test_playbook_evals.py` for the Kotlin port: the debloat classifier
 * over the 297-package REVVL 7 snapshot, the parsers over the recordings in
 * `tests/fixtures/playbooks/`, the risk scorer, and the tables against the
 * Python module's export.
 */
class PlaybooksTest {
    private val now: Instant = Instant.parse("2026-10-24T12:00:00Z")

    private fun snapshotPackages(): Map<String, Playbooks.Pkg> = Playbooks.parsePackages(Repo.snapshot.readText())

    private fun names(arr: JSONArray): List<String> = (0 until arr.length()).map { arr.getJSONObject(it).getString("pkg") }

    private fun strings(arr: JSONArray): List<String> = (0 until arr.length()).map { arr.getString(it) }

    /** The package column of one table in the REVVL debloat log. */
    private fun logTable(heading: String): Set<String> {
        val section = Repo.debloatLog.readText().substringAfter("## $heading").substringBefore("\n## ")
        return section.lines().filter { it.startsWith("| `") }.map { it.split("`")[1] }.toSet()
    }

    private fun sections(name: String): Map<String, String> = Playbooks.splitSections(Repo.fixture(name), "@@caelza:")

    // --- the debloat classifier over the REVVL 7 ------------------------------

    @Test
    fun snapshot_parses_to_the_297_packages_with_paths() {
        val pkgs = snapshotPackages()
        assertEquals(297, pkgs.size)
        assertTrue(pkgs.getValue("com.google.android.gms").path!!.startsWith("/"))
        assertTrue(pkgs.getValue("com.metro.minus1").path!!.endsWith(".apk"))
    }

    @Test
    fun the_logs_carrier_junk_lands_in_remove_or_disable() {
        val plan = Playbooks.debloatPlan(snapshotPackages().keys)
        val offered = HashMap<String, String>()
        for (cls in listOf("remove", "disable")) for (pkg in names(plan.getJSONArray(cls))) offered[pkg] = cls
        val carrier = setOf(
            "com.metro.minus1", "com.metropcs.metrozone", "com.ironsrc.aura.tmo",
            "com.nuance.nmc.sihome.metropcs", "com.vitastudio.mahjong", "in.playsimple.newwordsearch",
            "in.playsimple.triple.tile.matchgame.pair.three.puzzle.object.royale",
            "com.amazon.storm.lightning.client.aosp", "com.tmobile.pr.adapt",
            "com.tmobile.echolocate", "com.tmobile.echolocate.system", "com.tmobile.dm.cm", "com.tmobile.dm.ms.services",
        )
        assertTrue((carrier - offered.keys).toString(), offered.keys.containsAll(carrier))
        val telemetry = carrier.filter { it.startsWith("com.tmobile.echolocate") || it.startsWith("com.tmobile.dm") }.toSet()
        assertEquals(telemetry, offered.filter { it.value == "disable" && it.key in carrier }.keys)
        for (cls in listOf("remove", "disable")) {
            val arr = plan.getJSONArray(cls)
            for (i in 0 until arr.length()) {
                val item = arr.getJSONObject(i)
                assertTrue(item.getString("why").isNotEmpty())
                assertTrue(item.getString("reason").startsWith("phone-debloat: "))
            }
        }
    }

    @Test
    fun the_logs_google_apps_are_offered_as_optional_never_planned() {
        val plan = Playbooks.debloatPlan(snapshotPackages().keys)
        val optional = names(plan.getJSONArray("optional")).toSet()
        val google = (logTable("Uninstalled") + logTable("Disabled")).filter { it.startsWith("com.google.android") || it.startsWith("com.android.chrome") }.toSet()
        assertTrue((google - optional).toString(), optional.containsAll(google))
        val planned = (names(plan.getJSONArray("remove")) + names(plan.getJSONArray("disable"))).toSet()
        assertTrue((planned intersect google).isEmpty())
        assertTrue(optional.containsAll(setOf("com.tmobile.rsuapp", "com.tmobile.rsusrv", "com.tmobile.rsuadapter.qualcomm")))
        val arr = plan.getJSONArray("optional")
        for (i in 0 until arr.length()) assertFalse("optional packages carry no ready-made reason", arr.getJSONObject(i).has("reason"))
    }

    @Test
    fun nothing_the_phone_needs_is_ever_offered() {
        val plan = Playbooks.debloatPlan(snapshotPackages().keys)
        val offered = listOf("remove", "disable", "optional").flatMap { names(plan.getJSONArray(it)) }.toSet()
        val needed = setOf(
            "android", "com.android.systemui", "com.android.launcher3", "com.android.dialer", "com.android.phone",
            "com.android.settings", "com.android.carrierconfig", "com.android.vending", "com.google.android.gms",
            "com.google.android.gsf", "com.google.android.permissioncontroller", "com.google.android.setupwizard",
            "com.google.android.euicc", "com.google.android.webview", "com.google.android.tts",
            "com.google.android.inputmethod.latin", "com.google.android.as", "com.google.android.marvin.talkback",
            "com.tailscale.ipn", "com.qualcomm.qti.telephonyservice", "com.qti.phone", "vendor.qti.iwlan",
            "org.codeaurora.ims", "com.wingtech.carrierconfig", "com.android.providers.telephony",
        )
        assertTrue((needed intersect offered).toString(), (needed intersect offered).isEmpty())
        for (pkg in needed) assertEquals(pkg, "keep", Playbooks.classify(pkg).first)
        assertEquals("keep", Playbooks.classify("com.android.internal.display.cutout.emulation.hole").first)
        assertEquals("keep", Playbooks.classify("com.odm.euiccoverlay").first)
    }

    @Test
    fun counts_add_up_and_review_is_only_the_owners_own_apps() {
        val pkgs = snapshotPackages()
        val third = setOf("com.govee.home", "com.tailscale.ipn")
        val plan = Playbooks.debloatPlan(pkgs.keys, thirdParty = third, disabled = setOf("com.tmobile.echolocate"), keep = listOf("com.metro.minus1"))
        val listed = listOf("remove", "disable", "optional", "review").sumOf { plan.getJSONArray(it).length() }
        assertEquals(297, plan.getInt("total"))
        assertEquals(297, listed + plan.getInt("keep") + plan.getJSONArray("already_disabled").length())
        assertEquals(2, plan.getInt("third_party"))
        assertEquals(listOf("com.govee.home"), names(plan.getJSONArray("review")))
        assertTrue(plan.getJSONArray("review").getJSONObject(0).getString("why").startsWith("third-party app the list does not know"))
        assertEquals(listOf("com.tmobile.echolocate"), strings(plan.getJSONArray("already_disabled")))
        assertEquals(listOf("com.metro.minus1"), strings(plan.getJSONArray("pinned")))
        assertFalse("the owner's keep wins over the table", "com.metro.minus1" in names(plan.getJSONArray("remove")))
        val remove = plan.getJSONArray("remove")
        for (i in 0 until remove.length()) {
            val item = remove.getJSONObject(i)
            if (item.getString("pkg").startsWith("com.tmobile")) assertFalse(item.getBoolean("third_party"))
        }
    }

    @Test
    fun exact_names_win_over_patterns_and_the_first_pattern_wins() {
        assertEquals("remove" to Playbooks.REMOVE.getValue("com.tmobile.pr.adapt"), Playbooks.classify("com.tmobile.pr.adapt"))
        assertEquals("optional", Playbooks.classify("com.tmobile.vvm.application").first)
        assertEquals("optional", Playbooks.classify("com.facebook.katana").first)
        assertEquals("remove", Playbooks.classify("com.facebook.appmanager").first)
        assertEquals("remove", Playbooks.classify("com.dti.att").first)
        assertEquals("keep", Playbooks.classify("com.termux.api").first)
        assertEquals("" to "", Playbooks.classify("org.example.mine"))
    }

    // --- the parsers over recordings -------------------------------------------

    @Test
    fun foreground_parses_both_dumpsys_shapes() {
        val fg = Playbooks.parseForeground(Repo.fixture("window-popup.txt"))
        assertEquals("com.example.flashlightpro", fg.getString("package"))
        assertEquals("com.example.flashlightpro.ui.OfferActivity", fg.getString("activity"))
        val alt = Playbooks.parseForeground("    topResumedActivity=ActivityRecord{5e6f u0 com.android.launcher3/.uioverrides.QuickstepLauncher t7}")
        assertEquals("com.android.launcher3", alt.getString("package"))
        assertEquals("com.android.launcher3.uioverrides.QuickstepLauncher", alt.getString("activity"))
        val shade = Playbooks.parseForeground("  mCurrentFocus=Window{1a2b u0 NotificationShade}\n  mFocusedApp=null")
        assertTrue(shade.isNull("package"))
        assertEquals("the notification shade is open", shade.getString("note"))
        assertEquals("nothing has focus (screen off?)", Playbooks.parseForeground("  mCurrentFocus=null").getString("note"))
    }

    @Test
    fun package_appops_and_component_lists_parse() {
        val s = sections("suspects.txt")
        val info = Playbooks.parseDumpsysPackage(s.getValue("pkg com.example.flashlightpro"))
        assertEquals(false, info.system)
        assertEquals("3.2.1", info.version)
        assertEquals("2026-10-20 18:02:11", info.firstInstall)
        assertEquals("com.google.android.packageinstaller", info.installer)
        assertTrue("android.permission.SYSTEM_ALERT_WINDOW" in info.permissions)
        assertEquals(true, Playbooks.parseDumpsysPackage("    pkgFlags=[ SYSTEM HAS_CODE ]").system)
        assertEquals(
            mapOf("SYSTEM_ALERT_WINDOW" to "allow", "RUN_IN_BACKGROUND" to "allow", "REQUEST_INSTALL_PACKAGES" to "allow"),
            Playbooks.parseAppops(s.getValue("ops com.example.flashlightpro")),
        )
        assertEquals(setOf("com.example.flashlightpro"), Playbooks.parseComponentList(s.getValue("accessibility")))
        assertEquals(emptySet<String>(), Playbooks.parseComponentList(s.getValue("listeners")))
        assertEquals(
            setOf("com.corp.mdm", "com.other.app"),
            Playbooks.parseDeviceAdmins("    admin=com.corp.mdm/.AdminReceiver\n  ComponentInfo{com.other.app/.Admin}"),
        )
        val detail = Repo.fixture("foreground-detail.txt")
        assertEquals("com.google.android.packageinstaller", Playbooks.parsePackages(detail.substringBefore("@@caelza:pkg")).getValue("com.example.flashlightpro").installer)
    }

    @Test
    fun risk_scoring_separates_the_sideloaded_overlay_app_from_an_ordinary_one() {
        val s = sections("suspects.txt")
        val bad = Playbooks.riskFlags(
            "com.example.flashlightpro", installer = "com.google.android.packageinstaller",
            info = Playbooks.parseDumpsysPackage(s.getValue("pkg com.example.flashlightpro")),
            appops = Playbooks.parseAppops(s.getValue("ops com.example.flashlightpro")),
            accessibility = setOf("com.example.flashlightpro"), now = now,
        )
        assertEquals("high", bad.getString("risk"))
        assertTrue(bad.getBoolean("sideloaded"))
        assertEquals(setOf("sideloaded", "overlay", "accessibility", "install_packages", "sms", "recent"), strings(bad.getJSONArray("flags")).toSet())
        val dull = Playbooks.riskFlags(
            "com.cleaner.boost.master", installer = null,
            info = Playbooks.parseDumpsysPackage(s.getValue("pkg com.cleaner.boost.master")),
            appops = Playbooks.parseAppops(s.getValue("ops com.cleaner.boost.master")), now = now,
        )
        assertEquals("low", dull.getString("risk"))
        assertEquals(listOf("sideloaded"), strings(dull.getJSONArray("flags")))
        val play = Playbooks.riskFlags(
            "com.govee.home", installer = "com.android.vending",
            info = Playbooks.PkgInfo(permissions = listOf("android.permission.CAMERA")), appops = emptyMap(), now = now,
        )
        assertEquals("low", play.getString("risk"))
        assertFalse(play.getBoolean("sideloaded"))
        assertEquals(listOf("camera"), strings(play.getJSONArray("flags")))
        val trusted = Playbooks.riskFlags("com.termux", installer = null, info = Playbooks.PkgInfo(), appops = emptyMap(), now = now)
        assertEquals(0, trusted.getJSONArray("flags").length())
        assertFalse(trusted.getBoolean("sideloaded"))
    }

    @Test
    fun health_parses_the_whole_recording() {
        val h = Playbooks.parseHealth(Repo.fixture("health.txt"))
        assertEquals(
            canon(JSONObject("""{"manufacturer":"T-Mobile","model":"TMRV075G","android":"16","security_patch":"2026-09-05","sdk":"36"}""")),
            canon(h.getJSONObject("identity")),
        )
        assertEquals(
            canon(JSONObject("""{"percent":87,"status":"charging","health":"good","temperature_c":28.5,"plugged":true}""")),
            canon(h.getJSONObject("battery")),
        )
        assertEquals(canon(JSONObject("""{"size_gb":110.0,"used_gb":77.4,"free_gb":32.6,"used_percent":71}""")), canon(h.getJSONObject("storage")))
        assertEquals(canon(JSONObject("""{"total_mb":5555,"available_mb":2941,"used_percent":47}""")), canon(h.getJSONObject("memory")))
        assertEquals(canon(JSONObject("""{"seconds":193822,"text":"2d 5h 50m"}""")), canon(h.getJSONObject("uptime")))
        assertEquals(canon(JSONObject("""{"status":0,"status_text":"none","hottest_c":38.0}""")), canon(h.getJSONObject("thermal")))
        val top = h.getJSONArray("top")
        assertEquals(4, top.length())
        assertEquals(canon(JSONObject("""{"cpu":10.0,"name":"system_server"}""")), canon(top.getJSONObject(0)))
        assertEquals(canon(JSONObject("""{"fatal_exceptions":2,"processes":["com.example.flashlightpro"]}""")), canon(h.getJSONObject("crashes")))
        assertEquals(listOf("wlan0 192.168.1.23/24", "tun0 100.101.102.103/32"), strings(h.getJSONArray("network")))
        val setup = h.getJSONObject("setup")
        assertTrue(setup.getBoolean("wireless_debugging") && setup.getBoolean("developer_options") && setup.getBoolean("termux_installed"))
        assertTrue(setup.getBoolean("termux_api_installed") && !setup.getBoolean("termux_boot_installed") && setup.getBoolean("tailscale_installed"))
        assertTrue(setup.getBoolean("termux_battery_unrestricted") && !setup.getBoolean("termux_api_battery_unrestricted"))
        assertFalse(setup.getBoolean("stay_awake_plugged_in"))
        assertFalse(setup.getBoolean("animations_off"))
        assertEquals("green", setup.getString("verified_boot"))
        assertEquals(true, setup.getBoolean("bootloader_locked"))
        assertEquals(listOf("2 crash(es) in the crash log: com.example.flashlightpro"), strings(h.getJSONArray("attention")))
    }

    @Test
    fun health_attention_speaks_up_when_something_is_wrong() {
        val h = JSONObject(
            """{"battery":{"percent":9,"status":"discharging","temperature_c":44.0,"health":"overheat"},
               "storage":{"free_gb":1.2},"memory":{"available_mb":310},"thermal":{"status":3,"status_text":"severe"},
               "crashes":{"fatal_exceptions":0,"processes":[]},
               "setup":{"termux_installed":true,"termux_battery_unrestricted":false,"verified_boot":"orange"}}""",
        )
        assertEquals(
            listOf(
                "battery at 9% and discharging", "battery hot: 44.0 °C", "battery health: overheat",
                "only 1.2 GB free", "memory tight: 310 MB available", "thermal status severe",
                "Termux is not exempt from battery optimisation", "verified boot state: orange",
            ),
            Playbooks.healthAttention(h),
        )
        assertEquals("health script did not finish", Playbooks.parseHealth("garbage").getString("error"))
    }

    @Test
    fun device_admins_are_read_from_both_dump_shapes_and_the_grep_keeps_them() {
        val dump = "Current Device Policy Manager state:\n  Enabled Device Admins (User 0, provisioningState: 0):\n" +
            "    com.spy.app/.AdminReceiver:\n      uid=10234\n      policies:\n        force-lock\n" +
            "    com.corp.mdm/com.corp.mdm.Receiver:\n" +
            "  mDeviceOwner=admin=ComponentInfo{com.corp.mdm/com.corp.mdm.Receiver}\n"
        assertEquals(setOf("com.spy.app", "com.corp.mdm"), Playbooks.parseDeviceAdmins(dump))
        assertEquals(emptySet<String>(), Playbooks.parseDeviceAdmins(""))
        val grep = Regex(Playbooks.ADMIN_GREP)
        val kept = dump.lines().filter { grep.containsMatchIn(it) }
        assertEquals(
            listOf("    com.spy.app/.AdminReceiver:", "    com.corp.mdm/com.corp.mdm.Receiver:", "  mDeviceOwner=admin=ComponentInfo{com.corp.mdm/com.corp.mdm.Receiver}"),
            kept,
        )
    }

    @Test
    fun a_store_install_the_table_knows_as_a_preload_goes_to_review() {
        val pkgs = setOf("com.king.candycrushsaga", "com.aura.oobe.metro", "com.android.settings")
        val plan = Playbooks.debloatPlan(
            pkgs, thirdParty = setOf("com.king.candycrushsaga", "com.aura.oobe.metro"),
            installers = mapOf("com.king.candycrushsaga" to "com.android.vending", "com.aura.oobe.metro" to null),
        )
        assertEquals(listOf("com.aura.oobe.metro"), names(plan.getJSONArray("remove")))
        val review = plan.getJSONArray("review").getJSONObject(0)
        assertEquals("com.king.candycrushsaga", review.getString("pkg"))
        assertTrue("installed from com.android.vending" in review.getString("why"))
        assertEquals("com.android.vending", review.getString("installer"))
        assertTrue("com.king.candycrushsaga" in names(Playbooks.debloatPlan(pkgs, thirdParty = setOf("com.king.candycrushsaga")).getJSONArray("remove")))
    }

    @Test
    fun a_preload_is_not_a_sideload_and_the_permission_grep_keeps_the_late_ones() {
        val sysapp = Playbooks.riskFlags("com.metro.minus1", installer = null, info = Playbooks.PkgInfo(system = true), appops = emptyMap(), now = now)
        assertFalse(sysapp.getBoolean("sideloaded"))
        assertEquals(0, sysapp.getJSONArray("flags").length())
        assertTrue(sysapp.getBoolean("system"))
        val grep = Regex(Playbooks.SENSITIVE_PERMISSION_GREP)
        val perms = listOf(
            "android.permission.ACCESS_NETWORK_STATE", "android.permission.SEND_SMS",
            "android.permission.WRITE_SETTINGS", "android.permission.INTERNET", "android.permission.READ_SMS",
        )
        assertEquals(listOf("android.permission.SEND_SMS", "android.permission.WRITE_SETTINGS", "android.permission.READ_SMS"), perms.filter { grep.containsMatchIn(it) })
    }

    @Test
    fun positional_getprop_sections_keep_their_places() {
        assertEquals(listOf("TCL", "TMRV075G", "14", "", "34"), Playbooks.positional("TCL\nTMRV075G\n14\n\n34\n\n"))
        val checks = Playbooks.setupChecks(emptyMap(), "", "", "green\n\n0\n")
        assertEquals("green", checks.getString("verified_boot"))
        assertTrue(checks.isNull("bootloader_locked"))
        assertEquals(true, Playbooks.setupChecks(emptyMap(), "", "", "green\n1\n0\n").getBoolean("bootloader_locked"))
    }

    @Test
    fun the_exit_prefix_splits_off_and_the_lines_split_as_python_does() {
        assertEquals(0 to "package:a\n", Playbooks.stripExit("exit 0\npackage:a\n"))
        assertEquals(-1 to "shell timed out after 30s", Playbooks.stripExit("exit -1\nshell timed out after 30s"))
        assertEquals(null to "no prefix here", Playbooks.stripExit("no prefix here"))
        assertEquals(listOf("a", "b"), Playbooks.splitLines("a\nb\n"))
        assertEquals(listOf("a", "", "b"), Playbooks.splitLines("a\n\nb"))
    }

    // --- the tables are the Python module's -------------------------------------

    @Test
    fun the_tables_match_the_python_export() {
        val export = File(Repo.appFixtures, "debloat-tables.json").readText()
        assertEquals(
            "run scripts/android_body_fixtures.py, or port the table change to Playbooks.kt",
            canon(JSONObject(export)), canon(Playbooks.exportTables()),
        )
    }
}
