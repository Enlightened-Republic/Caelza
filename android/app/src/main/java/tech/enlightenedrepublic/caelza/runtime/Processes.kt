package tech.enlightenedrepublic.caelza.runtime

import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit

/**
 * A child process run to completion with a deadline it cannot defeat: its
 * output is drained on a helper thread while the caller waits with a timeout,
 * so a binary that neither exits nor closes stdout (a lock, a tty prompt, a
 * hang) is killed at the deadline instead of holding the caller forever, the
 * way Python's `subprocess.run(timeout=…)` behaves for the guard.
 */
object Processes {
    /** `exitCode` is null when the deadline passed and the child was killed; `output` is what it wrote until then. */
    class Outcome(val exitCode: Int?, val output: String)

    fun run(pb: ProcessBuilder, timeoutMs: Long): Outcome {
        val proc = pb.redirectErrorStream(true).start()
        proc.outputStream.close()
        val buf = ByteArrayOutputStream()
        val reader = Thread({
            try {
                proc.inputStream.use { it.copyTo(buf) }
            } catch (_: Exception) {
            }
        }, "caelza-proc-out").apply {
            isDaemon = true
            start()
        }
        val exited = proc.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
        if (!exited) proc.destroyForcibly()
        reader.join(if (exited) timeoutMs else 2_000)
        return Outcome(if (exited) proc.exitValue() else null, buf.toString(Charsets.UTF_8.name()))
    }
}
