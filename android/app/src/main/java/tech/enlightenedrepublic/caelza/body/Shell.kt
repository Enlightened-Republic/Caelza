package tech.enlightenedrepublic.caelza.body

/**
 * One process run as the shell user. On a Termux phone the Body gets that
 * through `adb shell`; in the app Shizuku gives it ([ShizukuShell]). The
 * tools never see which: [BodyShell] shapes every run the way `adb.run` in
 * `caelza_body/agent/adb.py` does (`exit N`, then the merged output, capped),
 * so the parsers and the recorded phone the tests replay are the same.
 */
interface Shell {
    /** Why nothing can run right now (Shizuku not running, no permission), or null when it can. */
    fun unavailable(): String? = null

    /**
     * Run `argv` as the shell user with stdin closed. Never throws for a
     * command that fails; throws [ShellUnavailable] when the privilege layer
     * is missing, and answers `timedOut` (exit -1) once `timeoutMs` passed.
     */
    fun exec(argv: List<String>, timeoutMs: Long): ExecResult
}

class ExecResult(
    val exit: Int,
    val stdout: ByteArray,
    val stderr: ByteArray = ByteArray(0),
    val timedOut: Boolean = false,
) {
    /** stdout then stderr, as text. */
    val merged: String get() = String(stdout, Charsets.UTF_8) + String(stderr, Charsets.UTF_8)
}

class ShellUnavailable(message: String) : Exception(message)

/** The adb wrapper's shape over a [Shell]: `exit N\n<output>`, capped. */
class BodyShell(val shell: Shell) {
    fun run(vararg argv: String, timeoutMs: Long = DEFAULT_TIMEOUT_MS, cap: Int? = CAP): String =
        exec(argv.toList(), timeoutMs, cap)

    /** `sh -c <script>` with stderr folded into stdout in order, as `adb shell <script>` prints it. */
    fun script(script: String, timeoutMs: Long = DEFAULT_TIMEOUT_MS, cap: Int? = CAP): String =
        exec(listOf("sh", "-c", SCRIPT_PRELUDE + script), timeoutMs, cap)

    fun exec(argv: List<String>, timeoutMs: Long = DEFAULT_TIMEOUT_MS, cap: Int? = CAP): String {
        shell.unavailable()?.let { return "exit 127\n$NEEDS_SHIZUKU: $it" }
        val result = try {
            shell.exec(argv, timeoutMs)
        } catch (e: ShellUnavailable) {
            return "exit 127\n$NEEDS_SHIZUKU: ${e.message}"
        }
        if (result.timedOut) return "exit -1\nshell timed out after ${timeoutMs / 1000}s"
        var out = result.merged
        if (cap != null && out.length > cap) out = out.take(cap) + "\n…(truncated)"
        return "exit ${result.exit}\n$out"
    }

    /** Raw stdout (a PNG), or null and why. stderr is dropped so no banner can prepend noise to the payload. */
    fun bytes(argv: List<String>, timeoutMs: Long): Pair<ByteArray?, String> {
        shell.unavailable()?.let { return null to "$NEEDS_SHIZUKU: $it" }
        val result = try {
            shell.exec(argv, timeoutMs)
        } catch (e: ShellUnavailable) {
            return null to "$NEEDS_SHIZUKU: ${e.message}"
        }
        if (result.timedOut) return null to "timed out after ${timeoutMs / 1000}s"
        if (result.exit != 0 || result.stdout.isEmpty()) return null to "exit ${result.exit}"
        return result.stdout to ""
    }

    companion object {
        /** adb.CAP: the merged-output cap for one run. */
        const val CAP = 8000
        const val DEFAULT_TIMEOUT_MS = 30_000L
        const val NEEDS_SHIZUKU = "needs Shizuku"
        /** Prepended to every script so stderr lands in stdout in order (what `adb shell` shows). */
        const val SCRIPT_PRELUDE = "exec 2>&1\n"
    }
}
