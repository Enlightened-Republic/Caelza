package tech.enlightenedrepublic.caelza.logs

import tech.enlightenedrepublic.caelza.body.BodyHome
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import java.io.File
import java.io.RandomAccessFile
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter

/**
 * The logs the app keeps and the bug report made from them (design §2 "Logs").
 *
 * The sources are the files the app already writes: the Runtime's `daemon.log`
 * (and the `.prev` the rotation leaves), `llama-server.log`, the installer's
 * output (`install.log`, appended by the shell and the first run), the probe
 * log beside the current binary, and the Body's audit log. [tail] reads the
 * end of one at a line boundary; [scrub] blanks what looks like a secret (an
 * API key, a bearer, a token in a config line or a URL), in the viewer and in
 * the report alike, so a screenshot or a share never carries one; [render] is
 * the report: a header about this phone, then every source's tail.
 */
object BugReport {
    const val INSTALL_LOG = "install.log"
    const val REDACTED = "[redacted]"
    /** How much of each log the viewer and the report show, from the end. */
    const val TAIL_BYTES = 64 * 1024
    /** The rotated `.prev` of a log gets this much in the report. */
    const val PREV_BYTES = 16 * 1024
    /** `install.log` rotates at this size (the daemon's own logs at RuntimeService.LOG_ROTATE_BYTES). */
    const val INSTALL_LOG_ROTATE_BYTES = 1L * 1024 * 1024
    /** The report is written under `cacheDir/bugreport/` and served through the FileProvider (res/xml/file_paths.xml). */
    const val REPORT_DIR = "bugreport"
    const val MISSING = "(no file yet)"

    /** One log: a short id for intents and chips, what the chip says, the file, its rotated predecessor, one line about it. */
    data class Source(val id: String, val label: String, val file: File, val previous: File? = null, val about: String)

    /** The logs this app keeps, in the order the viewer shows them. */
    fun sources(store: RuntimeStore, home: File): List<Source> {
        val logs = store.logsDir
        val body = File(home, BodyHome.DIR_NAME)
        return listOf(
            Source("daemon", "daemon.log", File(logs, "daemon.log"), File(logs, "daemon.log.prev"),
                "the Runtime's output (caelza daemon)"),
            Source("llama", "llama-server.log", File(logs, "llama-server.log"), File(logs, "llama-server.log.prev"),
                "the local model server"),
            Source("install", INSTALL_LOG, File(logs, INSTALL_LOG), File(logs, "$INSTALL_LOG.prev"),
                "the installer's output: releases found, checksums, probes"),
            Source("probe", "probe.log", File(store.versionDir(store.current ?: "none"), "probe.log"), null,
                "the current Runtime's trial gateway, from its install"),
            Source("body", "device-actions.log", File(body, BodyHome.AUDIT_LOG), null,
                "the Body's audit log: one line per destructive device action"),
        )
    }

    fun byId(sources: List<Source>, id: String?): Source = sources.firstOrNull { it.id == id } ?: sources.first()

    /**
     * The last `maxBytes` of `file`, cut forward to a line boundary and opened by a line
     * saying how much came before; the whole file when it fits; "" when there is none.
     */
    fun tail(file: File, maxBytes: Int = TAIL_BYTES): String {
        if (!file.isFile) return ""
        val size = file.length()
        if (size <= maxBytes) return file.readText(Charsets.UTF_8)
        val bytes = ByteArray(maxBytes)
        RandomAccessFile(file, "r").use { raf ->
            raf.seek(size - maxBytes)
            raf.readFully(bytes)
        }
        var text = String(bytes, Charsets.UTF_8)
        val cut = text.indexOf('\n')
        var skipped = size - maxBytes
        if (cut >= 0) {
            skipped += cut + 1
            text = text.substring(cut + 1)
        }
        return "… ${human(skipped)} earlier not shown\n$text"
    }

    /**
     * Blank what looks like a secret. The shapes: a key-ish name with `:` or `=` and a value
     * (`api_key = "…"`, `token: …`, `paired_tokens = ["…"]`, the admin-token header), a bearer,
     * the prefixes providers give their keys, a secret in a URL's query. Prose that merely says
     * "token" or "key", `require_pairing = true` and exit codes stay as they are.
     */
    fun scrub(text: String): String {
        var out = text
        for ((rx, replacement) in SCRUBS) out = rx.replace(out, replacement)
        return out
    }

    /** `"2026-11-01T08:35:00Z line"` appended to `file`, which rotates to `.prev` at [INSTALL_LOG_ROTATE_BYTES]. */
    fun append(file: File, line: String, now: Instant = Instant.now()) {
        try {
            file.parentFile?.mkdirs()
            if (file.length() > INSTALL_LOG_ROTATE_BYTES) file.renameTo(File(file.parentFile, file.name + ".prev"))
            file.appendText("${STAMP.format(now.atOffset(ZoneOffset.UTC))} $line\n")
        } catch (_: Exception) {
            // A log that cannot be written is not worth failing an install over.
        }
    }

    /** `caelza-bug-report-20261101-083500.txt`. */
    fun fileName(now: Instant = Instant.now()): String =
        "caelza-bug-report-${FILE_STAMP.format(now.atOffset(ZoneOffset.UTC))}.txt"

    /**
     * The report: a header (`header` lines, about this phone and what runs), then one section
     * per source with its path, size and scrubbed tail; a rotated predecessor gets a shorter one.
     */
    fun render(header: List<Pair<String, String>>, sources: List<Source>, now: Instant = Instant.now(),
               maxBytes: Int = TAIL_BYTES, prevBytes: Int = PREV_BYTES): String {
        val sb = StringBuilder()
        sb.append("# Caelza bug report\n")
        sb.append("generated: ").append(STAMP.format(now.atOffset(ZoneOffset.UTC))).append('\n')
        sb.append("secrets: blanked as $REDACTED before anything left the phone\n\n")
        sb.append("## This phone\n")
        for ((k, v) in header) sb.append(k).append(": ").append(scrub(v)).append('\n')
        for (source in sources) {
            section(sb, source.label, source.about, source.file, maxBytes)
            source.previous?.takeIf { it.isFile }?.let { section(sb, "${source.label} (previous)", "rotated before the current one", it, prevBytes) }
        }
        return sb.toString()
    }

    private fun section(sb: StringBuilder, label: String, about: String, file: File, maxBytes: Int) {
        sb.append("\n## ").append(label).append('\n')
        sb.append(about).append('\n')
        if (!file.isFile) {
            sb.append(file.path).append(": ").append(MISSING).append('\n')
            return
        }
        val size = file.length()
        sb.append(file.path).append(", ").append(human(size))
        if (size > maxBytes) sb.append(", last ").append(human(maxBytes.toLong()))
        sb.append("\n```\n")
        val body = scrub(tail(file, maxBytes))
        sb.append(body)
        if (!body.endsWith("\n")) sb.append('\n')
        sb.append("```\n")
    }

    /** `1.5 GiB`, `312 KiB`, `47 B`. */
    fun human(bytes: Long): String {
        if (bytes < 1024) return "$bytes B"
        val units = listOf("KiB", "MiB", "GiB", "TiB")
        var value = bytes.toDouble()
        var unit = -1
        while (value >= 1024 && unit < units.lastIndex) {
            value /= 1024
            unit++
        }
        return if (value >= 10) "${value.toInt()} ${units[unit]}" else "%.1f %s".format(value, units[unit])
    }

    private val STAMP = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss'Z'")
    private val FILE_STAMP = DateTimeFormatter.ofPattern("yyyyMMdd-HHmmss")

    private val KEYISH = "(?:api[_-]?keys?|secrets?|tokens?|passwords?|passwd|credentials?|authorization|pairing[_-]?codes?)"

    private val SCRUBS: List<Pair<Regex, String>> = listOf(
        // A bearer first, so `Authorization: Bearer …` then folds into one blank below.
        Regex("""(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+""") to "Bearer $REDACTED",
        // name = value / name: value: the name may follow `_`, `-` or `.` (paired_tokens, admin-token, x.api_key),
        // the value a bearer, a quoted string, an array or one word (stopping at `&`, so a URL's next field stays).
        Regex("""(?i)(?<![A-Za-z])($KEYISH)(\s*[:=]\s*)(?:Bearer\s+\S+|"[^"\n]*"|'[^'\n]*'|\[[^\]\n]*]|[^\s"',;&]+)""") to "$1$2$REDACTED",
        Regex("""\bsk-[A-Za-z0-9_-]{8,}""") to REDACTED,
        Regex("""\b(?:ghp|gho|ghu|ghs|github_pat|gsk|xoxb|xoxp|xapp)[_-][A-Za-z0-9_-]{8,}""") to REDACTED,
        Regex("""\bAIza[0-9A-Za-z_-]{20,}""") to REDACTED,
        Regex("""\b\d{8,10}:[A-Za-z0-9_-]{30,}""") to REDACTED,
        Regex("""(?i)([?&]$KEYISH=)[^&\s"']+""") to "$1$REDACTED",
    )
}
