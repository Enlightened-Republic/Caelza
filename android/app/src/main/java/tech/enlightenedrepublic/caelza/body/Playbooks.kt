package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import java.time.Duration
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.DateTimeParseException

/**
 * The phone playbooks' deterministic half, `caelza_body/agent/playbooks.py`
 * in Kotlin: the curated debloat list and its classifier, the parsers for
 * what the shell prints (`pm list packages`, `dumpsys package`, `dumpsys
 * window`, `appops get`, `dumpsys battery`, `df`, `/proc/meminfo` and the
 * rest of the health script), and the risk flags `device_suspects` scores.
 * Pure functions, no shell. [exportTables] is compared with the Python
 * module's export in both test suites, so the two lists cannot drift.
 */
object Playbooks {
    // --- the debloat list ---------------------------------------------------
    //
    // Four classes, from least to most reversible: remove (carrier app pushers,
    // adware, preloaded games), disable (carrier telemetry and device
    // management), optional (heavy but useful apps, the owner's call), keep
    // (the platform, never offered). Anything else is keep when it is a system
    // package and review when it is third-party. Exact names win over patterns;
    // the first matching pattern wins.

    val REMOVE: Map<String, String> = linkedMapOf(
        "com.ironsrc.aura.tmo" to "ironSource Aura: pushes carrier-sponsored apps and ads (140 MB live on the REVVL 7)",
        "com.tmobile.pr.adapt" to "T-Mobile 'PR adapt': silent app installs on behalf of the carrier",
        "com.metro.minus1" to "Metro '-1 screen' launcher feed (363 MB live)",
        "com.metropcs.metrozone" to "MetroZone: carrier offers and app promotion (237 MB live)",
        "com.nuance.nmc.sihome.metropcs" to "Nuance SiHome: carrier voice-assistant stub",
        "com.amazon.appmanager" to "Amazon app manager: installs Amazon apps in the background",
        "com.amazon.storm.lightning.client.aosp" to "Amazon Lightning: Fire TV remote stub, preloaded",
        "com.netflix.partner.activation" to "Netflix partner activation stub (the Netflix app itself is optional)",
        "com.facebook.appmanager" to "Facebook app manager: installs and updates Facebook apps silently",
        "com.facebook.services" to "Facebook services stub: background install helper",
        "com.facebook.system" to "Facebook system stub: background install helper",
    )

    val DISABLE: Map<String, String> = linkedMapOf(
        "com.tmobile.echolocate" to "T-Mobile network telemetry (157 MB live)",
        "com.tmobile.echolocate.system" to "T-Mobile network telemetry (76 MB live)",
        "com.tmobile.dm.cm" to "T-Mobile device management client",
        "com.tmobile.dm.ms.services" to "T-Mobile device management services",
        "com.verizon.mips.services" to "Verizon interactive services: carrier telemetry",
        "com.att.iqi" to "AT&T IQI: carrier telemetry",
        "com.sprint.ms.smf.services" to "Sprint mobile services framework: carrier telemetry",
    )

    val OPTIONAL: Map<String, String> = linkedMapOf(
        "com.google.android.googlequicksearchbox" to "the Google app, Discover feed and Assistant hotword (~400 MB live); disabling it also stops 'Hey Google'",
        "com.google.android.apps.googleassistant" to "Google Assistant",
        "com.google.android.youtube" to "YouTube (237 MB)",
        "com.google.android.apps.youtube.music" to "YouTube Music (184 MB)",
        "com.google.android.apps.chromecast.app" to "Google Home (165 MB)",
        "com.google.android.apps.messaging" to "Google Messages; the default SMS app on many phones",
        "com.android.chrome" to "Chrome (~750 MB with its sandboxes); Android System WebView is separate and stays",
        "com.google.android.safetycore" to "Google on-device content scanning for Messages",
        "com.google.android.gm" to "Gmail",
        "com.google.android.apps.docs" to "Google Drive",
        "com.google.android.apps.photos" to "Google Photos; often the default gallery",
        "com.google.android.apps.maps" to "Google Maps",
        "com.google.android.apps.tachyon" to "Google Meet (Duo)",
        "com.google.android.apps.bard" to "Gemini",
        "com.google.android.videos" to "Google TV / Play Movies",
        "com.google.android.apps.subscriptions.red" to "Google One",
        "com.google.android.apps.wellbeing" to "Digital Wellbeing",
        "com.google.android.apps.nbu.files" to "Files by Google",
        "com.google.android.apps.walletnfcrel" to "Google Wallet (tap to pay)",
        "com.google.android.projection.gearhead" to "Android Auto",
        "com.google.ar.core" to "Google Play Services for AR",
        "com.wingos.wingcamera" to "the OEM camera app; the Body reaches the camera through camera2 without it",
        "com.tmobile.rsuapp" to "T-Mobile remote SIM unlock; needed only to carrier-unlock the phone",
        "com.tmobile.rsusrv" to "T-Mobile remote SIM unlock service; needed only to carrier-unlock the phone",
        "com.tmobile.rsuadapter.qualcomm" to "T-Mobile remote SIM unlock adapter; needed only to carrier-unlock the phone",
        "com.google.android.apps.turbo" to "Device Health Services (adaptive battery); keep unless you know why not",
    )

    class Pattern(val regex: String, val cls: String, val why: String) {
        val compiled: Regex = Regex(regex)
    }

    /** `(regex, class, why)`, checked after the exact tables; the first match wins. */
    val PATTERNS: List<Pattern> = listOf(
        // the platform: never offered
        Pattern("""^android$""", "keep", "the framework"),
        Pattern("""^com\.android\.""", "keep", "AOSP"),
        Pattern(
            """^com\.google\.android\.(gms|gsf|vending|permissioncontroller|setupwizard|euicc|webview|packageinstaller|tts|as|ext|networkstack|modulemetadata|configupdater|captiveportallogin|cellbroadcast|providers|documentsui|contacts|deskclock|calculator|calendar|marvin|accessibility|overlay|safetycenter|odad|ondevicepersonalization|federatedcompute|rkpdapp|sdksandbox|adservices|appsearch|healthconnect|health|wifi|uwb|connectivity|hotspot2|partnersetup|onetimeinitializer|verifier|signature|photopicker|printservice|feedback|contactkeys|gmsintegration|inputmethod)(\.|$)""",
            "keep", "Google platform component",
        ),
        Pattern("""^com\.google\.android\.apps\.(restore|safetyhub|customization|wallpaper|adm)(\.|$)""", "keep", "Google platform component"),
        Pattern("""^com\.google\.mainline\.""", "keep", "Mainline module"),
        Pattern("""^(com\.qti|com\.qualcomm|vendor\.|org\.codeaurora)""", "keep", "radio / vendor component"),
        Pattern("""^com\.termux(\.|$)""", "keep", "Termux is the Body"),
        Pattern("""^com\.tailscale\.ipn$""", "keep", "Tailscale reaches the hub"),
        Pattern("""(\.overlay|\.rro|_rro)(\.|$)""", "keep", "resource overlay"),
        Pattern("""^(com\.oem|com\.odm|com\.vendor|com\.wingtech|com\.smartsoft|com\.factory)\.""", "keep", "OEM component"),
        // carrier app pushers / preloaded games / partner promos
        Pattern("""^com\.aura\.oobe""", "remove", "Aura out-of-box app pusher"),
        Pattern("""^(com\.dti\.|com\.digitalturbine\.)""", "remove", "Digital Turbine Ignite: carrier-sponsored app installer"),
        Pattern("""^com\.ironsrc\.""", "remove", "ironSource app pusher"),
        Pattern("""^(com\.metro\.|com\.metropcs\.)""", "remove", "Metro by T-Mobile promotion"),
        Pattern("""^in\.playsimple\.""", "remove", "preloaded game"),
        Pattern("""^com\.vitastudio\.""", "remove", "preloaded game"),
        Pattern("""^com\.king\.candycrush""", "remove", "preloaded game"),
        Pattern("""^com\.gameloft\.""", "remove", "preloaded game"),
        Pattern("""^(com\.booking|com\.tripadvisor|flipboard\.boxer)""", "remove", "partner promotion preload"),
        // useful carrier apps: the owner's call
        Pattern("""^com\.tmobile\.""", "optional", "T-Mobile app; keep it if you use it (voicemail, Scam Shield, the T-Life app)"),
        Pattern("""^(com\.vzw\.|com\.verizon\.)""", "optional", "Verizon app; keep it if you use it"),
        Pattern("""^com\.att\.""", "optional", "AT&T app; keep it if you use it"),
        Pattern("""^(com\.amazon\.|com\.netflix\.|com\.microsoft\.|com\.linkedin\.|com\.spotify\.|com\.facebook\.)""", "optional", "preloaded partner app; keep it if you use it"),
        Pattern("""^com\.samsung\.android\.(bixby|app\.spage|game\.)""", "optional", "Samsung extra; keep it if you use it"),
    )

    /** Installers that count as a store; anything else (the package installer, a browser, `null`, a preload) is sideloaded. */
    val STORE_INSTALLERS: Set<String> = setOf(
        "com.android.vending", "com.amazon.venezia", "com.sec.android.app.samsungapps",
        "org.fdroid.fdroid", "org.fdroid.basic", "com.aurora.store", "com.huawei.appmarket",
        "com.xiaomi.market", "com.oppo.market", "com.heytap.market",
    )

    /** Sideloaded on purpose on a Caelza phone; never a suspect. */
    val TRUSTED_SIDELOADS: List<Regex> = listOf(Regex("""^com\.termux(\.|$)"""), Regex("""^com\.tailscale\.ipn$"""))

    val SENSITIVE_PERMISSIONS: Map<String, String> = linkedMapOf(
        "android.permission.RECEIVE_SMS" to "sms", "android.permission.READ_SMS" to "sms",
        "android.permission.SEND_SMS" to "sms", "android.permission.READ_CALL_LOG" to "calls",
        "android.permission.CALL_PHONE" to "calls", "android.permission.RECORD_AUDIO" to "microphone",
        "android.permission.CAMERA" to "camera", "android.permission.ACCESS_FINE_LOCATION" to "location",
        "android.permission.READ_CONTACTS" to "contacts", "android.permission.QUERY_ALL_PACKAGES" to "app_list",
        "android.permission.PACKAGE_USAGE_STATS" to "usage_stats",
        "android.permission.REQUEST_INSTALL_PACKAGES" to "install_packages",
        "android.permission.SYSTEM_ALERT_WINDOW" to "overlay",
        "android.permission.BIND_ACCESSIBILITY_SERVICE" to "accessibility",
        "android.permission.BIND_DEVICE_ADMIN" to "device_admin",
        "android.permission.BIND_NOTIFICATION_LISTENER_SERVICE" to "notification_listener",
        "android.permission.WRITE_SETTINGS" to "write_settings",
    )

    /** The shell-side `grep -E` that keeps the sensitive permissions of a `dumpsys package` before the list is cut. */
    val SENSITIVE_PERMISSION_GREP: String =
        "\\.(" + SENSITIVE_PERMISSIONS.keys.map { it.substringAfterLast(".") }.sorted().joinToString("|") + ")$"

    /** The shell-side `grep -E` that keeps the admin lines of `dumpsys device_policy`. */
    const val ADMIN_GREP = """admin=|ComponentInfo|^ *[A-Za-z][A-Za-z0-9_.]*/[A-Za-z0-9_.$]*:$"""

    val FLAG_WEIGHT: Map<String, Int> = linkedMapOf(
        "sideloaded" to 1, "recent" to 1, "overlay" to 2, "accessibility" to 3, "device_admin" to 3,
        "notification_listener" to 1, "install_packages" to 1, "sms" to 2, "calls" to 1,
        "usage_stats" to 1, "microphone" to 0, "camera" to 0, "location" to 0, "contacts" to 0,
        "app_list" to 0, "write_settings" to 1,
    )

    /** Every remote script ends by echoing this; output without it was cut off. */
    const val END = "@@caelza:end"
    const val HEALTH_MARK = "@@caelza:"

    /** The shell the health tool runs on the phone, in one call; each section fenced by a marker line. */
    val HEALTH_SCRIPT: String =
        "echo '@@caelza:identity'; " +
            "getprop ro.product.manufacturer; getprop ro.product.model; getprop ro.build.version.release; " +
            "getprop ro.build.version.security_patch; getprop ro.build.version.sdk; " +
            "echo '@@caelza:boot'; getprop ro.boot.verifiedbootstate; getprop ro.boot.flash.locked; getprop ro.debuggable; " +
            "echo '@@caelza:battery'; dumpsys battery 2>/dev/null; " +
            "echo '@@caelza:storage'; df -k /data 2>/dev/null; " +
            "echo '@@caelza:memory'; head -5 /proc/meminfo; " +
            "echo '@@caelza:uptime'; cat /proc/uptime; " +
            "echo '@@caelza:thermal'; dumpsys thermalservice 2>/dev/null | grep -E 'Thermal Status|mStatus' | head -2; " +
            "for z in /sys/class/thermal/thermal_zone*/temp; do cat ${'$'}z 2>/dev/null; done | sort -n | tail -1; " +
            "echo '@@caelza:top'; top -b -n 1 -m 6 2>/dev/null | tail -n 8; " +
            "echo '@@caelza:crashes'; logcat -d -b crash -t 60 2>/dev/null | grep -E 'FATAL EXCEPTION|Process: ' | head -20; " +
            "echo '@@caelza:settings'; " +
            "for k in adb_wifi_enabled adb_enabled development_settings_enabled stay_on_while_plugged_in " +
            "window_animation_scale transition_animation_scale animator_duration_scale package_verifier_user_consent; " +
            "do echo \"${'$'}k=${'$'}(settings get global ${'$'}k 2>/dev/null)\"; done; " +
            "echo '@@caelza:whitelist'; dumpsys deviceidle whitelist 2>/dev/null | grep -E 'com\\.termux|com\\.tailscale'; " +
            "echo '@@caelza:packages'; pm list packages 2>/dev/null | grep -E 'com\\.termux|com\\.tailscale\\.ipn'; " +
            "echo '@@caelza:network'; ip -o -4 addr show 2>/dev/null | awk '{print ${'$'}2, ${'$'}4}'; " +
            "echo '@@caelza:end'"

    /** `(class, why)` for one package from the curated tables; `("", "")` when the lists say nothing about it. */
    fun classify(pkg: String): Pair<String, String> {
        REMOVE[pkg]?.let { return "remove" to it }
        DISABLE[pkg]?.let { return "disable" to it }
        OPTIONAL[pkg]?.let { return "optional" to it }
        for (p in PATTERNS) if (p.compiled.containsMatchIn(pkg)) return p.cls to p.why
        return "" to ""
    }

    fun isTrustedSideload(pkg: String): Boolean = TRUSTED_SIDELOADS.any { it.containsMatchIn(pkg) }

    /**
     * Sort every installed package into remove / disable / optional / keep /
     * review. `thirdParty` is `pm list packages -3`, `disabled` is `-d`
     * (already-disabled packages are reported, not planned), `keep` the owner's
     * never-touch list, `installers` `{pkg: installer}` from `-i`: a
     * third-party package installed from a store is the owner's own whatever
     * the table says, so it goes to review, never to remove or disable.
     */
    fun debloatPlan(
        packages: Collection<String>,
        thirdParty: Collection<String> = emptyList(),
        disabled: Collection<String> = emptyList(),
        keep: Collection<String> = emptyList(),
        installers: Map<String, String?> = emptyMap(),
    ): JSONObject {
        val third = thirdParty.toSet()
        val off = disabled.toSet()
        val pinned = keep.map { it.trim() }.filter { it.isNotEmpty() }.toSortedSet()
        val out = linkedMapOf("remove" to JSONArray(), "disable" to JSONArray(), "optional" to JSONArray(), "review" to JSONArray())
        var kept = 0
        val skipped = JSONArray()
        for (pkg in packages.toSortedSet()) {
            if (pkg in pinned) {
                kept++
                continue
            }
            val (cls, why) = classify(pkg)
            val store = if (pkg in third) installers[pkg] else null
            if ((cls == "remove" || cls == "disable") && store != null && store in STORE_INSTALLERS) {
                out.getValue("review").put(
                    JSONObject().put("pkg", pkg).put("third_party", true).put("installer", store)
                        .put("why", "the list calls it $why, but it was installed from $store, so it is the owner's own; yours to judge"),
                )
                continue
            }
            if (cls == "remove" || cls == "disable" || cls == "optional") {
                if (pkg in off) {
                    skipped.put(pkg)
                    continue
                }
                val item = JSONObject().put("pkg", pkg).put("why", why).put("third_party", pkg in third)
                if (cls != "optional") item.put("reason", "phone-debloat: $why")
                out.getValue(cls).put(item)
            } else if (cls == "keep" || pkg !in third) {
                kept++
            } else {
                out.getValue("review").put(JSONObject().put("pkg", pkg).put("why", "third-party app the list does not know; yours to judge"))
            }
        }
        return JSONObject()
            .put("total", packages.toSet().size)
            .put("third_party", third.size)
            .put("remove", out.getValue("remove"))
            .put("disable", out.getValue("disable"))
            .put("optional", out.getValue("optional"))
            .put("review", out.getValue("review"))
            .put("keep", kept)
            .put("already_disabled", skipped)
            .put("pinned", JSONArray(pinned.toList()))
    }

    // --- parsers for what the shell returns ---------------------------------

    private val EXIT_LINE = Regex("""exit (-?\d+)""")

    /** `adb.run` (and [BodyShell]) prefix the merged output with `exit N`; split that off. */
    fun stripExit(out: String): Pair<Int?, String> {
        val i = out.indexOf('\n')
        val first = if (i >= 0) out.substring(0, i) else out
        val rest = if (i >= 0) out.substring(i + 1) else ""
        val m = EXIT_LINE.matchEntire(first.trim()) ?: return null to out
        return m.groupValues[1].toInt() to rest
    }

    /** Python's `str.splitlines()`: no trailing empty element for text that ends in a newline. */
    fun splitLines(text: String): List<String> {
        val lines = text.lines()
        return if (lines.isNotEmpty() && lines.last().isEmpty()) lines.dropLast(1) else lines
    }

    data class Pkg(val path: String?, val installer: String?)

    private val INSTALLER = Regex("""\s+installer=(\S+)""")

    /** `pm list packages [-f] [-i]` → `{pkg: (path, installer)}`. */
    fun parsePackages(text: String): Map<String, Pkg> {
        val pkgs = LinkedHashMap<String, Pkg>()
        for (raw in splitLines(text)) {
            val line = raw.trim()
            if (!line.startsWith("package:")) continue
            var body = line.removePrefix("package:")
            var installer: String? = null
            INSTALLER.find(body)?.let { m ->
                installer = m.groupValues[1].takeUnless { it == "null" || it.isEmpty() }
                body = body.substring(0, m.range.first)
            }
            body = body.trim()
            var path: String? = null
            if ("=" in body && body.startsWith("/")) {
                val eq = body.lastIndexOf('=')
                path = body.substring(0, eq)
                body = body.substring(eq + 1)
            }
            if (body.isNotEmpty()) pkgs[body] = Pkg(path, installer)
        }
        return pkgs
    }

    private val FOCUS = Regex("""\bu\d+\s+([A-Za-z][\w.]*)/([\w.$]+)""")

    /**
     * The package and activity on screen, from `dumpsys window displays`
     * (`mCurrentFocus`, `mFocusedApp`) or `dumpsys activity activities`
     * (`topResumedActivity`, `ResumedActivity`). `package`, `activity` and
     * `note` are always present (JSON null when unknown).
     */
    fun parseForeground(text: String): JSONObject {
        val result = JSONObject().put("package", JSONObject.NULL).put("activity", JSONObject.NULL).put("note", JSONObject.NULL)
        var note: String? = null
        val lines = splitLines(text)
        for (key in listOf("mCurrentFocus", "mFocusedApp", "topResumedActivity", "ResumedActivity", "mResumedActivity")) {
            for (line in lines) {
                if (key !in line) continue
                val m = FOCUS.find(line)
                if (m != null) {
                    val pkg = m.groupValues[1]
                    var act = m.groupValues[2]
                    if (act.startsWith(".")) act = pkg + act
                    result.put("package", pkg).put("activity", act)
                    if (note != null) result.put("note", note)
                    return result
                }
                if (note != null) continue
                note = when {
                    "NotificationShade" in line || "StatusBar" in line -> "the notification shade is open"
                    "Keyguard" in line || "keyguard" in line -> "the lock screen is showing"
                    "=null" in line -> "nothing has focus (screen off?)"
                    else -> null
                }
            }
        }
        if (note != null) result.put("note", note)
        return result
    }

    data class PkgInfo(
        val system: Boolean? = null,
        val firstInstall: String? = null,
        val lastUpdate: String? = null,
        val version: String? = null,
        val installer: String? = null,
        val permissions: List<String> = emptyList(),
    )

    private val SYSTEM_FLAG = Regex("""\bSYSTEM\b""")

    /** The few `dumpsys package <pkg>` fields the playbooks use. */
    fun parseDumpsysPackage(text: String): PkgInfo {
        var system: Boolean? = null
        var first: String? = null
        var last: String? = null
        var version: String? = null
        var installer: String? = null
        val permissions = mutableListOf<String>()
        for (raw in splitLines(text)) {
            val line = raw.trim()
            when {
                line.startsWith("installerPackageName=") || line.startsWith("installInitiatingPackageName=") -> {
                    val v = line.substringAfter("=").trim()
                    if (v.isNotEmpty() && v != "null" && installer == null) installer = v
                }
                line.startsWith("firstInstallTime=") -> first = line.substringAfter("=").trim()
                line.startsWith("lastUpdateTime=") -> last = line.substringAfter("=").trim()
                line.startsWith("versionName=") -> version = line.substringAfter("=").trim()
                line.startsWith("pkgFlags=[") || line.startsWith("flags=[") ->
                    system = SYSTEM_FLAG.containsMatchIn(line.substringAfter("["))
                line.startsWith("android.permission.") -> {
                    val perm = line.substringBefore(":").split(Regex("\\s+")).first()
                    if (perm !in permissions) permissions += perm
                }
            }
        }
        return PkgInfo(system, first, last, version, installer, permissions)
    }

    private val APPOP = Regex("""^\s*([A-Z_]+):\s*([a-z]+)""")

    /** `appops get <pkg>` → `{OP: mode}`. */
    fun parseAppops(text: String): Map<String, String> {
        val ops = LinkedHashMap<String, String>()
        for (raw in splitLines(text)) APPOP.find(raw)?.let { ops[it.groupValues[1]] = it.groupValues[2] }
        return ops
    }

    /** `settings get secure enabled_accessibility_services` and friends: `pkg/Class:pkg2/Class2` → the packages. */
    fun parseComponentList(text: String): Set<String> {
        val t = text.trim()
        if (t.isEmpty() || t == "null") return emptySet()
        return t.split(":").filter { it.isNotBlank() }.map { it.substringBefore("/") }.toSet()
    }

    private val ADMIN_LINE = Regex("""^\s*([A-Za-z][\w.]*)/[\w.$]+:\s*$""", RegexOption.MULTILINE)
    private val ADMIN_COMPONENT = Regex("""ComponentInfo\{([\w.]+)/""")
    private val ADMIN_EQUALS = Regex("""admin=([\w.]+)/""")

    /** Packages named as device admins in `dumpsys device_policy`: enabled admins (`pkg/.Receiver:`) and owners (`admin=ComponentInfo{pkg/...}`). */
    fun parseDeviceAdmins(text: String): Set<String> =
        ADMIN_COMPONENT.findAll(text).map { it.groupValues[1] }.toSet() +
            ADMIN_EQUALS.findAll(text).map { it.groupValues[1] }.toSet() +
            ADMIN_LINE.findAll(text).map { it.groupValues[1] }.toSet()

    private val INSTALL_TIME: DateTimeFormatter = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss")
    private val NOT_PERMISSION_FLAGS = setOf("overlay", "accessibility", "device_admin", "notification_listener", "install_packages")

    /** Score one third-party package: `flags` are the reasons, `risk` low / medium / high. */
    fun riskFlags(
        pkg: String,
        installer: String?,
        info: PkgInfo,
        appops: Map<String, String>,
        accessibility: Set<String> = emptySet(),
        admins: Set<String> = emptySet(),
        listeners: Set<String> = emptySet(),
        now: Instant? = null,
        recentDays: Int = 30,
    ): JSONObject {
        val flags = mutableListOf<String>()
        if ((installer == null || installer !in STORE_INSTALLERS) && !isTrustedSideload(pkg) && info.system != true) flags += "sideloaded"
        if (appops["SYSTEM_ALERT_WINDOW"] == "allow") flags += "overlay"
        if (pkg in accessibility) flags += "accessibility"
        if (pkg in admins) flags += "device_admin"
        if (pkg in listeners) flags += "notification_listener"
        if (appops["REQUEST_INSTALL_PACKAGES"] == "allow") flags += "install_packages"
        for (perm in info.permissions) {
            val tag = SENSITIVE_PERMISSIONS[perm] ?: continue
            if (tag !in flags && tag !in NOT_PERMISSION_FLAGS) flags += tag
        }
        val first = info.firstInstall
        if (first != null && now != null) {
            try {
                val installed = LocalDateTime.parse(first.take(19), INSTALL_TIME).toInstant(ZoneOffset.UTC)
                if (Duration.between(installed, now) <= Duration.ofDays(recentDays.toLong())) flags += "recent"
            } catch (_: DateTimeParseException) {
            }
        }
        val score = flags.sumOf { FLAG_WEIGHT[it] ?: 0 }
        val risk = if (score >= 5) "high" else if (score >= 2) "medium" else "low"
        return JSONObject()
            .put("pkg", pkg)
            .put("installer", installer ?: JSONObject.NULL)
            .put("sideloaded", "sideloaded" in flags)
            .put("system", info.system == true)
            .put("first_install", first ?: JSONObject.NULL)
            .put("last_update", info.lastUpdate ?: JSONObject.NULL)
            .put("version", info.version ?: JSONObject.NULL)
            .put("flags", JSONArray(flags))
            .put("score", score)
            .put("risk", risk)
    }

    // --- health -------------------------------------------------------------

    private val BATTERY_STATUS = mapOf(1 to "unknown", 2 to "charging", 3 to "discharging", 4 to "not charging", 5 to "full")
    private val BATTERY_HEALTH = mapOf(1 to "unknown", 2 to "good", 3 to "overheat", 4 to "dead", 5 to "over voltage", 6 to "failure", 7 to "cold")
    private val THERMAL_TEXT = listOf("none", "light", "moderate", "severe", "critical", "emergency", "shutdown")

    fun splitSections(text: String, mark: String = HEALTH_MARK): Map<String, String> {
        val sections = LinkedHashMap<String, String>()
        var current: String? = null
        for (line in splitLines(text)) {
            val t = line.trim()
            if (t.startsWith(mark)) {
                current = t.substring(mark.length)
                sections[current] = ""
            } else if (current != null) {
                sections[current] = sections[current] + line + "\n"
            }
        }
        return sections
    }

    private fun kvColon(text: String): Map<String, String> {
        val out = LinkedHashMap<String, String>()
        for (raw in splitLines(text)) if (":" in raw) {
            val t = raw.trim()
            out[t.substringBefore(":").trim()] = t.substringAfter(":").trim()
        }
        return out
    }

    private fun lines(text: String): List<String> = splitLines(text).map { it.trim() }.filter { it.isNotEmpty() }

    /** One value per line with the positions kept: `getprop` prints an empty line for an unset property. */
    fun positional(text: String): List<String> {
        val out = splitLines(text).map { it.trim() }.toMutableList()
        while (out.isNotEmpty() && out.last().isEmpty()) out.removeAt(out.size - 1)
        return out
    }

    private fun round1(v: Double): Double = Math.round(v * 10) / 10.0

    fun parseBattery(text: String): JSONObject {
        val kv = kvColon(text)
        return JSONObject()
            .put("percent", kv["level"]?.toIntOrNull() ?: JSONObject.NULL)
            .put("status", kv["status"]?.toIntOrNull()?.let { BATTERY_STATUS[it] ?: "unknown" } ?: JSONObject.NULL)
            .put("health", kv["health"]?.toIntOrNull()?.let { BATTERY_HEALTH[it] ?: "unknown" } ?: JSONObject.NULL)
            .put("temperature_c", kv["temperature"]?.toIntOrNull()?.let { it / 10.0 } ?: JSONObject.NULL)
            .put("plugged", listOf("AC powered", "USB powered", "Wireless powered").any { kv[it]?.lowercase() == "true" })
    }

    fun parseDf(text: String): JSONObject {
        for (line in splitLines(text).drop(1)) {
            val parts = line.split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (parts.size < 5) continue
            val size = parts[1].toLongOrNull()
            val used = parts[2].toLongOrNull()
            val avail = parts[3].toLongOrNull()
            if (size == null || used == null || avail == null) continue
            val gb = 1024.0 * 1024
            val pct = parts[4].trimEnd('%')
            return JSONObject()
                .put("size_gb", round1(size / gb))
                .put("used_gb", round1(used / gb))
                .put("free_gb", round1(avail / gb))
                .put("used_percent", if (pct.isNotEmpty() && pct.all { it.isDigit() }) pct.toInt() else JSONObject.NULL)
        }
        return JSONObject()
    }

    private val MEMINFO = Regex("""^(\w+):\s+(\d+)\s*kB""")

    fun parseMeminfo(text: String): JSONObject {
        val kv = HashMap<String, Long>()
        for (raw in splitLines(text)) MEMINFO.find(raw.trim())?.let { kv[it.groupValues[1]] = it.groupValues[2].toLong() }
        val total = kv["MemTotal"] ?: return JSONObject()
        val out = JSONObject().put("total_mb", total / 1024)
        kv["MemAvailable"]?.let { avail ->
            out.put("available_mb", avail / 1024)
            out.put("used_percent", kotlin.math.round(100 * (1 - avail.toDouble() / total)).toInt())
        }
        return out
    }

    fun parseUptime(text: String): JSONObject {
        val secs = text.trim().split(Regex("\\s+")).firstOrNull()?.toDoubleOrNull() ?: return JSONObject()
        val total = secs.toLong()
        val days = total / 86400
        val hours = total % 86400 / 3600
        val rem = total % 3600
        return JSONObject().put("seconds", total).put("text", "${days}d ${hours}h ${rem / 60}m")
    }

    private val THERMAL = Regex("""Thermal Status:\s*(\d+)|mStatus=(\d+)""")

    fun parseThermal(text: String): JSONObject {
        val out = JSONObject()
        THERMAL.find(text)?.let { m ->
            val status = m.groupValues[1].ifEmpty { m.groupValues[2] }.toInt()
            out.put("status", status).put("status_text", THERMAL_TEXT[minOf(status, 6)])
        }
        val nums = lines(text).filter { it.all { c -> c.isDigit() } }.map { it.toLong() }
        nums.maxOrNull()?.let { hottest -> out.put("hottest_c", if (hottest > 1000) round1(hottest / 1000.0) else hottest) }
        return out
    }

    fun parseTop(text: String): JSONArray {
        val rows = JSONArray()
        var headerSeen = false
        var cpuIdx: Int? = null
        for (raw in splitLines(text)) {
            val parts = raw.split(Regex("\\s+")).filter { it.isNotEmpty() }
            if (parts.isEmpty()) continue
            if (!headerSeen) {
                if ("PID" in parts && parts.any { "CPU" in it }) {
                    headerSeen = true
                    val i = parts.indexOfFirst { "CPU" in it }
                    // toybox prints the state and CPU columns under one header, `S[%CPU]`; the rows keep them as two fields.
                    cpuIdx = if (parts[i].startsWith("S")) i + 1 else i
                }
                continue
            }
            val idx = cpuIdx ?: continue
            if (parts.size <= idx) continue
            val cpu = parts[idx].trimEnd('%').toDoubleOrNull() ?: continue
            rows.put(JSONObject().put("cpu", cpu).put("name", parts.last()))
        }
        return rows
    }

    private val PROCESS = Regex("""Process:\s*([\w.:]+)""")

    fun parseCrashes(text: String): JSONObject {
        val fatal = splitLines(text).count { "FATAL EXCEPTION" in it }
        val procs = PROCESS.findAll(text).map { it.groupValues[1] }.toSortedSet()
        return JSONObject().put("fatal_exceptions", fatal).put("processes", JSONArray(procs.toList()))
    }

    fun parseSettingsBlock(text: String): Map<String, String> {
        val out = LinkedHashMap<String, String>()
        for (raw in splitLines(text)) if ("=" in raw) {
            val t = raw.trim()
            out[t.substringBefore("=")] = t.substringAfter("=").trim()
        }
        return out
    }

    /** The new-phone checklist as booleans the SOP can read off. */
    fun setupChecks(settings: Map<String, String>, whitelist: String, packages: String, boot: String): JSONObject {
        val pkgs = parsePackages(packages)
        val bootLines = positional(boot)
        val scales = listOf("window_animation_scale", "transition_animation_scale", "animator_duration_scale").map { settings[it] ?: "" }
        val stayOn = settings["stay_on_while_plugged_in"]
        return JSONObject()
            .put("wireless_debugging", settings["adb_wifi_enabled"] == "1")
            .put("adb_enabled", settings["adb_enabled"] == "1")
            .put("developer_options", settings["development_settings_enabled"] == "1")
            .put("stay_awake_plugged_in", stayOn == null || stayOn !in setOf("", "0", "null"))
            .put("animations_off", if (scales.any { it.isNotEmpty() }) scales.all { it == "0" || it == "0.0" } else false)
            .put("play_protect_consent", settings["package_verifier_user_consent"] == "1")
            .put("termux_installed", "com.termux" in pkgs)
            .put("termux_api_installed", "com.termux.api" in pkgs)
            .put("termux_boot_installed", "com.termux.boot" in pkgs)
            .put("tailscale_installed", "com.tailscale.ipn" in pkgs)
            .put("termux_battery_unrestricted", ",com.termux," in whitelist || whitelist.trimEnd().endsWith(",com.termux"))
            .put("termux_api_battery_unrestricted", ",com.termux.api," in whitelist)
            .put("verified_boot", bootLines.getOrNull(0)?.ifEmpty { null } ?: JSONObject.NULL)
            .put(
                "bootloader_locked",
                if (bootLines.size > 1 && bootLines[1] in setOf("0", "1")) bootLines[1] == "1" else JSONObject.NULL,
            )
    }

    /** The whole [HEALTH_SCRIPT] output → one JSON-ready object. */
    fun parseHealth(text: String): JSONObject {
        val s = splitSections(text)
        if ("end" !in s) return JSONObject().put("error", "health script did not finish").put("sections", JSONArray(s.keys.sorted()))
        val ident = positional(s["identity"] ?: "")
        fun at(i: Int): Any = ident.getOrNull(i)?.ifEmpty { null } ?: JSONObject.NULL
        val identity = JSONObject()
            .put("manufacturer", at(0)).put("model", at(1)).put("android", at(2)).put("security_patch", at(3)).put("sdk", at(4))
        val settings = parseSettingsBlock(s["settings"] ?: "")
        val network = lines(s["network"] ?: "").filter { !it.startsWith("lo ") }
        val out = JSONObject()
            .put("identity", identity)
            .put("battery", parseBattery(s["battery"] ?: ""))
            .put("storage", parseDf(s["storage"] ?: ""))
            .put("memory", parseMeminfo(s["memory"] ?: ""))
            .put("uptime", parseUptime(s["uptime"] ?: ""))
            .put("thermal", parseThermal(s["thermal"] ?: ""))
            .put("top", parseTop(s["top"] ?: ""))
            .put("crashes", parseCrashes(s["crashes"] ?: ""))
            .put("network", JSONArray(network))
            .put("setup", setupChecks(settings, s["whitelist"] ?: "", s["packages"] ?: "", s["boot"] ?: ""))
        out.put("attention", JSONArray(healthAttention(out)))
        return out
    }

    /** What a human should look at first, in plain words. */
    fun healthAttention(h: JSONObject): List<String> {
        val notes = mutableListOf<String>()
        val b = h.optJSONObject("battery") ?: JSONObject()
        if (!b.isNull("percent") && b.getInt("percent") <= 15 && b.optString("status") == "discharging") {
            notes += "battery at ${b.getInt("percent")}% and discharging"
        }
        if (!b.isNull("temperature_c") && b.getDouble("temperature_c") >= 42) notes += "battery hot: ${num(b.get("temperature_c"))} °C"
        if (!b.isNull("health") && b.getString("health") !in setOf("good", "unknown")) notes += "battery health: ${b.getString("health")}"
        val st = h.optJSONObject("storage") ?: JSONObject()
        if (!st.isNull("free_gb") && st.getDouble("free_gb") < 2) notes += "only ${num(st.get("free_gb"))} GB free"
        val mem = h.optJSONObject("memory") ?: JSONObject()
        if (!mem.isNull("available_mb") && mem.getLong("available_mb") < 400) notes += "memory tight: ${mem.getLong("available_mb")} MB available"
        val th = h.optJSONObject("thermal") ?: JSONObject()
        if (th.optInt("status", 0) >= 3) notes += "thermal status ${th.optString("status_text")}"
        val cr = h.optJSONObject("crashes") ?: JSONObject()
        if (cr.optInt("fatal_exceptions", 0) > 0) {
            val procs = cr.optJSONArray("processes") ?: JSONArray()
            val shown = (0 until minOf(procs.length(), 4)).map { procs.getString(it) }
            notes += "${cr.getInt("fatal_exceptions")} crash(es) in the crash log: ${shown.joinToString(", ")}"
        }
        val setup = h.optJSONObject("setup") ?: JSONObject()
        if (setup.optBoolean("termux_installed") && !setup.optBoolean("termux_battery_unrestricted")) {
            notes += "Termux is not exempt from battery optimisation"
        }
        if (!setup.isNull("verified_boot")) {
            val vb = setup.getString("verified_boot")
            if (vb.isNotEmpty() && vb != "green") notes += "verified boot state: $vb"
        }
        return notes
    }

    /** A number the way Python prints it in an f-string: `44.0`, `1.2`, `9`. */
    private fun num(v: Any): String = when (v) {
        is Double -> if (v == Math.floor(v) && !v.isInfinite()) "%.1f".format(v) else v.toString()
        is Float -> num(v.toDouble())
        else -> v.toString()
    }

    /** The tables as the Python module exports them (`python -m caelza_body.agent.playbooks`), for the parity tests. */
    fun exportTables(): JSONObject = JSONObject()
        .put("remove", JSONObject(REMOVE))
        .put("disable", JSONObject(DISABLE))
        .put("optional", JSONObject(OPTIONAL))
        .put("patterns", JSONArray(PATTERNS.map { JSONObject().put("regex", it.regex).put("class", it.cls).put("why", it.why) }))
        .put("store_installers", JSONArray(STORE_INSTALLERS.sorted()))
        .put("trusted_sideloads", JSONArray(TRUSTED_SIDELOADS.map { it.pattern }))
        .put("sensitive_permissions", JSONObject(SENSITIVE_PERMISSIONS))
        .put("flag_weight", JSONObject(FLAG_WEIGHT))
        .put("sensitive_permission_grep", SENSITIVE_PERMISSION_GREP)
        .put("admin_grep", ADMIN_GREP)
        .put("health_script", HEALTH_SCRIPT)
}
