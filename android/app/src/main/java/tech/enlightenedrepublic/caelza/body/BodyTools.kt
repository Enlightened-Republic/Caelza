package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.time.Instant

/**
 * The Body's `device` tools for the phone the app runs on, with the contract
 * of `caelza_body/agent/tools/device.py` and `tools/playbook.py`: the same
 * names, descriptions and argument schemas (pinned against the Python
 * server's `list-tools` output in the tests), the same safety classes
 * (`mcp_server.READ_ONLY` / `DESTRUCTIVE` / `NEUTRAL`), a `reason` on every
 * destructive call written to the audit log, and the package snapshot before
 * a removal. Only `self` answers: the fleet tools (`device_pair`,
 * `device_unpair`, `device_join`, `device_tag`) stay with the Python Body,
 * which has `adb` and the registry.
 */
class BodyTools(
    private val shell: BodyShell,
    private val home: BodyHome,
    private val now: () -> Instant = Instant::now,
) {
    enum class Safety { READ_ONLY, DESTRUCTIVE, NEUTRAL }

    class ToolResult(val text: String, val images: List<Pair<File, String>> = emptyList()) {
        val isError: Boolean get() = text.startsWith("error:")
    }

    /** One tool as the server lists it: the spec plus how to run it here. */
    class Tool(val spec: Spec, internal val run: (JSONObject) -> ToolResult) {
        val name: String get() = spec.name

        fun annotations(): JSONObject = JSONObject()
            .put("readOnlyHint", spec.safety == Safety.READ_ONLY)
            .put("destructiveHint", spec.safety == Safety.DESTRUCTIVE)
            .put("idempotentHint", spec.safety == Safety.READ_ONLY)
            .put("openWorldHint", false)

        fun mcp(): JSONObject = JSONObject()
            .put("name", spec.name)
            .put("description", spec.description)
            .put("inputSchema", JSONObject(spec.schema))
            .put("annotations", annotations())
    }

    class Spec(val name: String, val safety: Safety, val description: String, val schema: String)

    private val lock = Any()

    val tools: List<Tool> = SPECS.map { spec -> Tool(spec, runnerFor(spec.name)) }

    fun tool(name: String): Tool? = tools.firstOrNull { it.name == name }

    /** Dispatch one call: validate against the schema, run it under the one-phone lock, surface exceptions as text. */
    fun call(name: String, arguments: JSONObject?): ToolResult {
        val tool = tool(name) ?: return ToolResult("error: unknown tool $name")
        val args = arguments ?: JSONObject()
        validate(JSONObject(tool.spec.schema), args)?.let { return ToolResult("error: input validation: $it") }
        return synchronized(lock) {
            try {
                tool.run(args)
            } catch (e: Exception) {
                ToolResult("error: ${e.javaClass.simpleName}: ${e.message}")
            }
        }
    }

    // --- the tools ----------------------------------------------------------

    private fun runnerFor(name: String): (JSONObject) -> ToolResult = when (name) {
        "device_list" -> { _ -> deviceList() }
        "device_shell" -> { a -> onSelf(a) { shell.script(a.getString("cmd")) } }
        "device_screencap" -> { a -> screencap(device(a)) }
        "device_ui_dump" -> { a -> onSelf(a) { shell.script("uiautomator dump /sdcard/u.xml && cat /sdcard/u.xml") } }
        "device_packages" -> { a -> onSelf(a) { shell.exec(listOf("pm", "list", "packages") + shlexSplit(a.optString("flags", "-3"))) } }
        "device_logcat" -> { a ->
            onSelf(a) {
                val filter = a.optString("filter", "")
                shell.exec(listOf("logcat", "-d", "-t", a.optInt("lines", 200).toString()) + if (filter.isNotEmpty()) listOf(filter) else emptyList())
            }
        }
        "device_settings" -> { a -> onSelf(a) { shell.run("settings", "get", a.getString("ns"), a.getString("key")) } }
        "device_input" -> { a -> onSelf(a) { input(a) } }
        "device_settings_put" -> { a ->
            onSelf(a) {
                val ns = a.getString("ns")
                val key = a.getString("key")
                val value = a.getString("value")
                home.logAction(device(a), "device_settings_put", "$ns $key=$value", a.getString("reason"))
                shell.run("settings", "put", ns, key, value)
            }
        }
        "device_appops" -> { a ->
            onSelf(a) {
                val pkg = a.getString("pkg")
                val op = a.getString("op")
                val mode = a.getString("mode")
                home.logAction(device(a), "device_appops", "$pkg $op=$mode", a.getString("reason"))
                shell.run("appops", "set", pkg, op, mode)
            }
        }
        "device_uninstall" -> { a -> onSelf(a) { removal(device(a), "device_uninstall", a.getString("pkg"), a.getString("reason"), listOf("pm", "uninstall", "--user", "0")) } }
        "device_disable" -> { a -> onSelf(a) { removal(device(a), "device_disable", a.getString("pkg"), a.getString("reason"), listOf("pm", "disable-user", "--user", "0")) } }
        "device_debloat_plan" -> { a -> onSelf(a) { debloatPlan(device(a), a.optString("keep", "")) } }
        "device_suspects" -> { a -> onSelf(a) { suspects(device(a), a.optInt("days", 30)) } }
        "device_foreground" -> { a -> onSelf(a) { foreground(device(a)) } }
        "device_health" -> { a -> onSelf(a) { health(device(a)) } }
        else -> { _ -> ToolResult("error: unknown tool $name") }
    }

    private fun device(a: JSONObject): String = a.optString("device", "self")

    /** The Python `_unknown(device)` guard: this Body is one phone. */
    private fun unknown(device: String): String? = if (device == "self") null else "error: unknown device '$device'"

    private inline fun onSelf(a: JSONObject, body: () -> Any): ToolResult {
        unknown(device(a))?.let { return ToolResult(it) }
        return when (val out = body()) {
            is ToolResult -> out
            is String -> ToolResult(out)
            else -> ToolResult(out.toString())
        }
    }

    private fun deviceList(): ToolResult = ToolResult(
        JSONObject().put(
            "self",
            JSONObject().put("kind", "self").put("reachable", shell.shell.unavailable() == null).put("groups", JSONArray()),
        ).toString(),
    )

    private fun screencap(device: String): ToolResult {
        unknown(device)?.let { return ToolResult(it) }
        val (data, why) = shell.bytes(listOf("screencap", "-p"), SCREENCAP_TIMEOUT_MS)
        if (data == null) return ToolResult("error: screencap failed: $why")
        if (!isPng(data)) return ToolResult("error: screencap did not return a PNG: ${String(data, 0, minOf(80, data.size), Charsets.ISO_8859_1)}")
        val file = home.captureFile(device)
        file.writeBytes(data)
        return ToolResult("screenshot captured", listOf(file to "image/png"))
    }

    private fun input(a: JSONObject): String {
        fun arg(key: String): String = if (a.has(key) && !a.isNull(key)) a.get(key).toString() else "None"
        return when (val action = a.getString("action")) {
            "tap" -> shell.run("input", "tap", arg("x"), arg("y"))
            "swipe" -> shell.run("input", "swipe", arg("x"), arg("y"), arg("x2"), arg("y2"))
            "text" -> shell.run("input", "text", arg("text"))
            "keyevent" -> shell.run("input", "keyevent", arg("key"))
            else -> "error: unknown input action '$action'"
        }
    }

    /** Snapshot the full package list, refuse when it holds none, audit, then run `pm ... <pkg>`. */
    private fun removal(device: String, tool: String, pkg: String, reason: String, argv: List<String>): String {
        val snapOut = shell.exec(listOf("pm", "list", "packages", "-f"), SNAPSHOT_TIMEOUT_MS, cap = null)
        val snap = home.snapshotFile(device)
        snap.writeText(snapOut)
        if ("package:" !in snapOut) {
            home.logAction(device, tool, "$pkg (snapshot $snap — ABORTED: no package list)", reason)
            return "error: snapshot failed, not removing $pkg: ${snapOut.take(200)}"
        }
        home.logAction(device, tool, "$pkg (snapshot $snap)", reason)
        return shell.exec(argv + pkg)
    }

    // --- the playbook reads (tools/playbook.py) -------------------------------

    /** `(error, output)`: one remote script, uncapped; every script ends in `echo '@@caelza:end'`. */
    private fun remoteScript(dev: String, script: String, timeoutMs: Long = 60_000): Pair<String?, String> {
        val out = shell.script(script, timeoutMs, cap = null)
        val (rc, body) = Playbooks.stripExit(out)
        val text = body.trim()
        val lower = text.lowercase()
        val shellsOwn = text.isEmpty() || lower.startsWith("error") || lower.startsWith(BodyShell.NEEDS_SHIZUKU.lowercase()) || lower.startsWith("shell timed out")
        if (rc == -1 || (rc != null && rc != 0 && shellsOwn)) {
            return "error: the shell on '$dev': ${text.take(200).ifEmpty { "exit $rc" }}" to ""
        }
        if (Playbooks.END !in body) return "error: the shell on '$dev': the script was cut off before it finished: '${text.takeLast(200)}'" to ""
        return null to body
    }

    private fun installers(dev: String, flags: String = "-3"): Pair<String?, Map<String, Playbooks.Pkg>> {
        val (err, out) = remoteScript(dev, "pm list packages -i $flags; echo '@@caelza:end'")
        if (err != null) return err to emptyMap()
        return null to Playbooks.parsePackages(out)
    }

    private fun debloatPlan(device: String, keep: String): Any {
        val (e1, everything) = remoteScript(device, "pm list packages; echo '@@caelza:end'")
        if (e1 != null) return e1
        val all = Playbooks.parsePackages(everything)
        if (all.isEmpty()) return "error: `pm list packages` returned no packages on '$device': ${everything.take(200)}"
        val (e2, third) = installers(device, "-3")
        if (e2 != null) return e2
        val (e3, disabled) = remoteScript(device, "pm list packages -d; echo '@@caelza:end'")
        if (e3 != null) return e3
        val plan = Playbooks.debloatPlan(
            all.keys, third.keys, Playbooks.parsePackages(disabled).keys,
            if (keep.isNotEmpty()) keep.split(",") else emptyList(),
            third.mapValues { it.value.installer },
        )
        plan.put("device", device)
        plan.put(
            "how",
            "remove: device_uninstall(pkg, reason) per package, which snapshots the package list first; " +
                "disable: device_disable(pkg, reason); optional: only what the owner names; " +
                "review: show the owner, touch nothing. Both reversible: `pm install-existing` / `pm enable`.",
        )
        return plan
    }

    private fun suspects(device: String, days: Int): Any {
        val (err, third) = installers(device, "-3")
        if (err != null) return err
        val candidates = third.filter { (pkg, meta) ->
            (meta.installer == null || meta.installer !in Playbooks.STORE_INSTALLERS) && !Playbooks.isTrustedSideload(pkg)
        }.keys.sorted()
        val inspected = candidates.take(MAX_SUSPECTS)
        val (e2, out) = remoteScript(device, suspectsScript(inspected), 120_000)
        if (e2 != null) return e2
        val sections = Playbooks.splitSections(out, "@@caelza:")
        val accessibility = Playbooks.parseComponentList(sections["accessibility"] ?: "")
        val listeners = Playbooks.parseComponentList(sections["listeners"] ?: "")
        val admins = Playbooks.parseDeviceAdmins(sections["admins"] ?: "")
        val at = now()
        val rows = inspected.map { pkg ->
            Playbooks.riskFlags(
                pkg, installer = third.getValue(pkg).installer,
                info = Playbooks.parseDumpsysPackage(sections["pkg $pkg"] ?: ""),
                appops = Playbooks.parseAppops(sections["ops $pkg"] ?: ""),
                accessibility = accessibility, admins = admins, listeners = listeners, now = at, recentDays = days,
            )
        }.sortedWith(compareBy({ -it.getInt("score") }, { it.getString("pkg") }))
        return JSONObject()
            .put("device", device)
            .put("third_party", third.size)
            .put("sideloaded", candidates.size)
            .put("inspected", inspected.size)
            .put("truncated", candidates.size > inspected.size)
            .put("suspects", JSONArray(rows))
            .put("accessibility_services", JSONArray(accessibility.sorted()))
            .put("device_admins", JSONArray(admins.sorted()))
            .put("notification_listeners", JSONArray(listeners.sorted()))
            .put(
                "how",
                "a popup or ad you did not ask for usually comes from a `high` row: device_disable(pkg, reason) " +
                    "stops it (reversible), device_appops(pkg, 'SYSTEM_ALERT_WINDOW', 'deny', reason) takes the " +
                    "overlay away without removing the app. Show the owner the list before either.",
            )
    }

    private fun foreground(device: String): Any {
        val (err, out) = remoteScript(
            device,
            "dumpsys window displays 2>/dev/null | grep -E 'mCurrentFocus|mFocusedApp'; " +
                "dumpsys activity activities 2>/dev/null | grep -E 'topResumedActivity|ResumedActivity' | head -3; " +
                "echo '@@caelza:end'",
        )
        if (err != null) return err
        val fg = Playbooks.parseForeground(out)
        fg.put("device", device)
        val pkg = if (fg.isNull("package")) null else fg.getString("package")
        if (pkg == null) {
            if (fg.isNull("note")) fg.put("note", "no foreground activity found")
            return fg
        }
        val q = shellQuote(pkg)
        val (e2, detail) = remoteScript(
            device,
            "pm list packages -i $q 2>/dev/null; " +
                "echo '@@caelza:pkg'; dumpsys package $q 2>/dev/null | " +
                "grep -E 'installerPackageName|installInitiatingPackageName|firstInstallTime|lastUpdateTime|versionName|pkgFlags=|^ *flags=' | head -12; " +
                "dumpsys package $q 2>/dev/null | grep -oE 'android\\.permission\\.[A-Z_]+' | grep -E '${Playbooks.SENSITIVE_PERMISSION_GREP}' | sort -u; " +
                "echo '@@caelza:ops'; appops get $q 2>/dev/null; " +
                "echo '@@caelza:accessibility'; settings get secure enabled_accessibility_services; " +
                "echo '@@caelza:admins'; dumpsys device_policy 2>/dev/null | grep -E '${Playbooks.ADMIN_GREP}' | head -20; " +
                "echo '@@caelza:end'",
        )
        if (e2 != null) {
            fg.put("error", e2)
            return fg
        }
        val head = detail.substringBefore("@@caelza:pkg")
        val rest = detail.substringAfter("@@caelza:pkg", "")
        var installer = Playbooks.parsePackages(head)[pkg]?.installer
        val sections = Playbooks.splitSections("@@caelza:pkg$rest", "@@caelza:")
        val info = Playbooks.parseDumpsysPackage(sections["pkg"] ?: "")
        if (installer == null) installer = info.installer
        val flags = Playbooks.riskFlags(
            pkg, installer = installer, info = info, appops = Playbooks.parseAppops(sections["ops"] ?: ""),
            accessibility = Playbooks.parseComponentList(sections["accessibility"] ?: ""),
            admins = Playbooks.parseDeviceAdmins(sections["admins"] ?: ""), now = now(),
        )
        for (key in flags.keys()) fg.put(key, flags.get(key))
        if (flags.getBoolean("system")) {
            fg.put("note", "a system app; not a sideload")
        } else if (flags.getBoolean("sideloaded")) {
            fg.put("note", "sideloaded: not from an app store")
        }
        return fg
    }

    private fun health(device: String): Any {
        val (err, out) = remoteScript(device, Playbooks.HEALTH_SCRIPT, 90_000)
        if (err != null) return err
        val health = Playbooks.parseHealth(out)
        health.put("device", device)
        if (health.has("error")) {
            val sections = health.optJSONArray("sections") ?: JSONArray()
            return "error: ${health.getString("error")} on '$device' (sections: ${(0 until sections.length()).map { sections.getString(it) }.joinToString(", ")})"
        }
        return health
    }

    companion object {
        const val SCREENCAP_TIMEOUT_MS = 30_000L
        const val SNAPSHOT_TIMEOUT_MS = 30_000L
        /** `device_suspects` inspects at most this many sideloaded packages per call. */
        const val MAX_SUSPECTS = 25

        /** The `device` group's tools that stay with the Python Body: they need `adb` or the fleet registry. */
        val NOT_SERVED = listOf("device_pair", "device_unpair", "device_join", "device_tag")

        private const val DEVICE_ONLY = """{"type":"object","properties":{"device":{"type":"string","default":"self"}}}"""

        /** Registration order as in the Python Body: device.py first, then the playbook reads. */
        val SPECS: List<Spec> = listOf(
            Spec(
                "device_list", Safety.READ_ONLY,
                "List the fleet: this phone ('self'), the phones paired over ADB (kind 'adb') and the joined Bodies " +
                    "reached over HTTP (kind 'http'), each with reachability and groups.",
                """{"type":"object","properties":{}}""",
            ),
            Spec(
                "device_shell", Safety.DESTRUCTIVE,
                "Run a shell command on a device via adb ('self' = this phone).",
                """{"type":"object","properties":{"cmd":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["cmd"]}""",
            ),
            Spec("device_screencap", Safety.READ_ONLY, "Capture a PNG screenshot of a device and attach it to the reply.", DEVICE_ONLY),
            Spec("device_ui_dump", Safety.READ_ONLY, "Dump the current on-screen UI hierarchy as XML.", DEVICE_ONLY),
            Spec(
                "device_packages", Safety.READ_ONLY,
                "List installed packages ('-3' third-party only by default).",
                """{"type":"object","properties":{"flags":{"type":"string","default":"-3"},"device":{"type":"string","default":"self"}}}""",
            ),
            Spec(
                "device_logcat", Safety.READ_ONLY,
                "Fetch recent logcat lines from a device.",
                """{"type":"object","properties":{"filter":{"type":"string"},"lines":{"type":"integer","default":200},"device":{"type":"string","default":"self"}}}""",
            ),
            Spec(
                "device_settings", Safety.READ_ONLY,
                "Read a device setting: `settings get <ns> <key>`.",
                """{"type":"object","properties":{"ns":{"type":"string"},"key":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["ns","key"]}""",
            ),
            Spec(
                "device_input", Safety.NEUTRAL,
                "Inject an input event: tap / swipe / text / keyevent.",
                """{"type":"object","properties":{"action":{"type":"string","enum":["tap","swipe","text","keyevent"]},"device":{"type":"string","default":"self"},"x":{"type":"integer"},"y":{"type":"integer"},"x2":{"type":"integer"},"y2":{"type":"integer"},"text":{"type":"string"},"key":{"type":"string"}},"required":["action"]}""",
            ),
            Spec(
                "device_settings_put", Safety.DESTRUCTIVE,
                "DANGEROUS: write a device setting (`settings put <ns> <key> <value>`). Requires a reason (audit-logged).",
                """{"type":"object","properties":{"ns":{"type":"string"},"key":{"type":"string"},"value":{"type":"string"},"reason":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["ns","key","value","reason"]}""",
            ),
            Spec(
                "device_appops", Safety.DESTRUCTIVE,
                "DANGEROUS: set an app-ops mode (`appops set <pkg> <op> <mode>`). Requires a reason (audit-logged).",
                """{"type":"object","properties":{"pkg":{"type":"string"},"op":{"type":"string"},"mode":{"type":"string"},"reason":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["pkg","op","mode","reason"]}""",
            ),
            Spec(
                "device_uninstall", Safety.DESTRUCTIVE,
                "DANGEROUS: uninstall a package for user 0. Snapshots the package list first and audit-logs the reason.",
                """{"type":"object","properties":{"pkg":{"type":"string"},"reason":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["pkg","reason"]}""",
            ),
            Spec(
                "device_disable", Safety.DESTRUCTIVE,
                "DANGEROUS: disable a package for user 0. Snapshots the package list first and audit-logs the reason.",
                """{"type":"object","properties":{"pkg":{"type":"string"},"reason":{"type":"string"},"device":{"type":"string","default":"self"}},"required":["pkg","reason"]}""",
            ),
            Spec(
                "device_debloat_plan", Safety.READ_ONLY,
                "Plan a debloat: sort every installed package into remove (carrier app pushers, adware, preloaded games), " +
                    "disable (carrier telemetry and device management), optional (heavy first-party apps the owner may want), " +
                    "keep (the platform) and review (third-party apps the list does not know). Read-only; nothing is removed. " +
                    "`keep` is a comma-separated list of packages to leave alone whatever the list says.",
                """{"type":"object","properties":{"device":{"type":"string","default":"self"},"keep":{"type":"string","default":""}}}""",
            ),
            Spec(
                "device_suspects", Safety.READ_ONLY,
                "Malware triage, read-only: the third-party packages that did not come from an app store, each with who " +
                    "installed it, when, and the risk flags that matter (draws over other apps, accessibility service, device " +
                    "admin, notification listener, can install packages, SMS or call permissions, installed in the last `days`). " +
                    "Sorted highest risk first. Termux and Tailscale are known and skipped.",
                """{"type":"object","properties":{"device":{"type":"string","default":"self"},"days":{"type":"integer","default":30}}}""",
            ),
            Spec(
                "device_foreground", Safety.READ_ONLY,
                "What is on the screen right now: the foreground package and activity, who installed it, whether it is a " +
                    "system app or sideloaded, and its risk flags. Read-only. The first thing to call when the owner reports a " +
                    "popup they did not ask for.",
                DEVICE_ONLY,
            ),
            Spec(
                "device_health", Safety.READ_ONLY,
                "One read of the phone's health: model and patch level, battery (level, charging, temperature, health), " +
                    "storage, memory, uptime, heat, the top CPU users, recent crashes, network addresses, and the new-phone " +
                    "setup checklist (wireless debugging, Termux and Termux:API installed and exempt from battery optimisation, " +
                    "Tailscale, developer options, animations). `attention` lists what to look at first. Read-only.",
                DEVICE_ONLY,
            ),
        )

        fun names(safety: Safety): List<String> = SPECS.filter { it.safety == safety }.map { it.name }

        private val PNG_MAGIC = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A)

        fun isPng(data: ByteArray): Boolean = data.size >= 8 && (0 until 8).all { data[it] == PNG_MAGIC[it] }

        private val SAFE_WORD = Regex("""^[\w@%+=:,./-]+$""")

        /** `shlex.quote`: unchanged when safe, else single-quoted. */
        fun shellQuote(s: String): String = if (s.isNotEmpty() && SAFE_WORD.matches(s)) s else "'" + s.replace("'", "'\"'\"'") + "'"

        /** `shlex.split` for the flags a caller passes (`-3`, `-f -i`, a quoted word). */
        fun shlexSplit(text: String): List<String> {
            val out = mutableListOf<String>()
            val cur = StringBuilder()
            var inWord = false
            var quote: Char? = null
            var i = 0
            while (i < text.length) {
                val c = text[i]
                when {
                    quote != null -> if (c == quote) quote = null else if (c == '\\' && quote == '"' && i + 1 < text.length) { cur.append(text[++i]) } else cur.append(c)
                    c == '\'' || c == '"' -> { quote = c; inWord = true }
                    c == '\\' && i + 1 < text.length -> { cur.append(text[++i]); inWord = true }
                    c.isWhitespace() -> if (inWord) { out += cur.toString(); cur.setLength(0); inWord = false }
                    else -> { cur.append(c); inWord = true }
                }
                i++
            }
            if (inWord) out += cur.toString()
            return out
        }

        /** The script `device_suspects` sends: one `dumpsys package` + `appops get` per package, then the lists. */
        fun suspectsScript(pkgs: List<String>): String {
            val parts = mutableListOf<String>()
            for (pkg in pkgs) {
                val q = shellQuote(pkg)
                parts += "echo '@@caelza:pkg $pkg'; d=$(dumpsys package $q 2>/dev/null); " +
                    "echo \"${'$'}d\" | grep -E 'installerPackageName|installInitiatingPackageName|firstInstallTime|lastUpdateTime|versionName|pkgFlags=|^ *flags=' | head -8; " +
                    "echo \"${'$'}d\" | grep -oE 'android\\.permission\\.[A-Z_]+' | grep -E '${Playbooks.SENSITIVE_PERMISSION_GREP}' | sort -u; " +
                    "echo '@@caelza:ops $pkg'; appops get $q 2>/dev/null"
            }
            parts += "echo '@@caelza:accessibility'; settings get secure enabled_accessibility_services"
            parts += "echo '@@caelza:listeners'; settings get secure enabled_notification_listeners"
            parts += "echo '@@caelza:admins'; dumpsys device_policy 2>/dev/null | grep -E '${Playbooks.ADMIN_GREP}' | head -20"
            parts += "echo '@@caelza:end'"
            return parts.joinToString("; ")
        }

        /**
         * The slice of JSON Schema the Body's schemas use: `required`, property
         * `type`, `enum`. The message, or null when the arguments fit.
         */
        fun validate(schema: JSONObject, args: JSONObject): String? {
            schema.optJSONArray("required")?.let { required ->
                for (i in 0 until required.length()) {
                    val key = required.getString(i)
                    if (!args.has(key) || args.isNull(key)) return "'$key' is a required property"
                }
            }
            val props = schema.optJSONObject("properties") ?: return null
            for (key in args.keys()) {
                val spec = props.optJSONObject(key) ?: continue
                val value = args.get(key)
                val type = spec.optString("type", "")
                val ok = when (type) {
                    "string" -> value is String
                    "integer" -> value is Int || value is Long || (value is Number && value.toDouble() == Math.floor(value.toDouble()))
                    "number" -> value is Number
                    "boolean" -> value is Boolean
                    "object" -> value is JSONObject
                    "array" -> value is JSONArray
                    else -> true
                }
                if (!ok) return "$key: $value is not of type '$type'"
                spec.optJSONArray("enum")?.let { allowed ->
                    val values = (0 until allowed.length()).map { allowed.get(it) }
                    if (values.none { it == value }) return "$key: $value is not one of $values"
                }
            }
            return null
        }
    }
}
