package tech.enlightenedrepublic.caelza.body

import java.io.File
import java.nio.file.Files
import java.nio.file.attribute.PosixFilePermissions
import java.security.SecureRandom
import java.time.Instant
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.util.Base64

/**
 * The Body's state dir inside the app, laid out as `$CAELZA_BODY_HOME`
 * (`~/.caelza-body`) is on a Termux phone, so what the Python Body writes the
 * app writes in the same place under the same names:
 *
 * ```
 * run/http-token                the bearer token the Runtime sends (0600, created once)
 * logs/device-actions.log       one line per destructive call: ts, device, tool, detail, reason
 * snapshots/<device>-<ns>.txt   the full package list taken before a removal
 * tmp/screen-<device>-<ns>.png  captures handed back as image content
 * ```
 */
class BodyHome(val dir: File) {
    val tokenFile: File get() = File(dir, TOKEN_FILE)
    val auditLog: File get() = File(dir, AUDIT_LOG)
    val snapshots: File get() = File(dir, "snapshots")
    val tmp: File get() = File(dir, "tmp")

    /** The token in `run/http-token`, created when the file is missing; never regenerated while it holds one. */
    fun token(): String {
        tokenFile.takeIf { it.isFile }?.readText()?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        val token = freshToken()
        writeSecret(tokenFile, token + "\n")
        return token
    }

    /** One audit line for a state-changing device action (`device._log_action`). */
    fun logAction(device: String, tool: String, detail: String, reason: String) {
        auditLog.parentFile?.mkdirs()
        val ts = DateTimeFormatter.ISO_OFFSET_DATE_TIME.format(Instant.now().atOffset(ZoneOffset.UTC))
        auditLog.appendText("$ts\t$device\t$tool\t$detail\t$reason\n")
    }

    fun snapshotFile(device: String): File {
        snapshots.mkdirs()
        return File(snapshots, "$device-${nanos()}.txt")
    }

    fun captureFile(device: String, ext: String = "png"): File {
        tmp.mkdirs()
        return File(tmp, "screen-$device-${nanos()}.$ext")
    }

    /** Drop captures older than a day and all but the newest [KEEP_SNAPSHOTS] snapshots; never fails. */
    fun prune(now: Long = System.currentTimeMillis()) {
        try {
            tmp.listFiles()?.filter { it.isFile && it.lastModified() < now - TMP_MAX_AGE_MS }?.forEach { it.delete() }
        } catch (_: Exception) {
        }
        try {
            snapshots.listFiles()?.filter { it.isFile }?.sortedByDescending { it.lastModified() }
                ?.drop(KEEP_SNAPSHOTS)?.forEach { it.delete() }
        } catch (_: Exception) {
        }
    }

    companion object {
        /** Under the app's HOME (its files dir), as `~/.caelza-body` is under a Termux HOME. */
        const val DIR_NAME = ".caelza-body"
        const val TOKEN_FILE = "run/http-token"
        const val AUDIT_LOG = "logs/device-actions.log"
        const val TMP_MAX_AGE_MS = 24L * 3600 * 1000
        const val KEEP_SNAPSHOTS = 20

        /** `time.time_ns()`: the names the Python Body gives snapshots and captures. */
        fun nanos(): Long = Instant.now().let { it.epochSecond * 1_000_000_000L + it.nano }

        /** A url-safe token that starts with a letter or digit, so it pastes after `--token` (`fleet.fresh_token`). */
        fun freshToken(random: SecureRandom = SecureRandom()): String {
            while (true) {
                val bytes = ByteArray(32).also { random.nextBytes(it) }
                val token = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
                if (token[0] != '-' && token[0] != '_') return token
            }
        }

        /** A file nobody else can read: the directory 0700, the file 0600 (`fleet.write_secret`). */
        fun writeSecret(file: File, text: String) {
            file.parentFile?.mkdirs()
            setPosix(file.parentFile, "rwx------")
            if (!file.exists()) file.createNewFile()
            setPosix(file, "rw-------")
            file.writeText(text)
            setPosix(file, "rw-------")
        }

        private fun setPosix(file: File?, perms: String) {
            if (file == null) return
            try {
                Files.setPosixFilePermissions(file.toPath(), PosixFilePermissions.fromString(perms))
            } catch (_: Exception) {
                // a filesystem without POSIX modes: the app sandbox is the lock there
            }
        }
    }
}
