package tech.enlightenedrepublic.caelza.body

import rikka.shizuku.Shizuku
import rikka.shizuku.ShizukuRemoteProcess
import tech.enlightenedrepublic.caelza.shizuku.ShizukuStatus
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.lang.reflect.InvocationTargetException
import java.util.concurrent.TimeUnit

/**
 * The shell user through Shizuku: `Shizuku.newProcess` runs a command inside
 * the Shizuku server, which holds adb's uid, so `pm`, `settings`, `appops`,
 * `input`, `screencap` and `dumpsys` answer exactly as they do over `adb
 * shell` from Termux (vision §3.3). The API library keeps `newProcess`
 * private (its public face is a bound UserService), so it is reached by
 * reflection; a library that moves it, a Shizuku that is not running or a
 * permission not granted all read as "needs Shizuku" in the tool's answer,
 * never as a crash.
 */
class ShizukuShell : Shell {
    override fun unavailable(): String? {
        val state = ShizukuStatus.state()
        return if (state == ShizukuStatus.State.READY) null else ShizukuStatus.label(state)
    }

    override fun exec(argv: List<String>, timeoutMs: Long): ExecResult {
        unavailable()?.let { throw ShellUnavailable(it) }
        val process = newProcess(argv.toTypedArray())
        val stdout = ByteArrayOutputStream()
        val stderr = ByteArrayOutputStream()
        val readers = listOf(drain(process.inputStream, stdout), drain(process.errorStream, stderr))
        try {
            process.outputStream.close()
        } catch (_: Exception) {
        }
        val finished = try {
            (process as? ShizukuRemoteProcess)?.waitForTimeout(timeoutMs, TimeUnit.MILLISECONDS)
                ?: process.waitFor(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (_: InterruptedException) {
            false
        }
        if (!finished) {
            try {
                process.destroy()
            } catch (_: Exception) {
            }
            readers.forEach { it.join(READER_GRACE_MS) }
            return ExecResult(-1, stdout.toByteArray(), stderr.toByteArray(), timedOut = true)
        }
        readers.forEach { it.join(READER_GRACE_MS) }
        val exit = try {
            process.exitValue()
        } catch (_: IllegalThreadStateException) {
            -1
        }
        return ExecResult(exit, stdout.toByteArray(), stderr.toByteArray())
    }

    private fun drain(from: InputStream, into: ByteArrayOutputStream): Thread =
        Thread({
            try {
                from.use { it.copyTo(into) }
            } catch (_: Exception) {
                // the process was destroyed under us; what was read is kept
            }
        }, "caelza-body-shell").apply {
            isDaemon = true
            start()
        }

    private fun newProcess(cmd: Array<String>): Process {
        val method = try {
            Shizuku::class.java.getDeclaredMethod(
                "newProcess", Array<String>::class.java, Array<String>::class.java, String::class.java,
            )
        } catch (_: NoSuchMethodException) {
            throw ShellUnavailable("this Shizuku API library has no newProcess")
        }
        method.isAccessible = true
        return try {
            method.invoke(null, cmd, null, null) as Process
        } catch (e: InvocationTargetException) {
            val cause = e.cause
            throw ShellUnavailable(cause?.message ?: cause?.javaClass?.simpleName ?: "newProcess failed")
        } catch (e: ReflectiveOperationException) {
            throw ShellUnavailable(e.message ?: "newProcess failed")
        }
    }

    companion object {
        const val READER_GRACE_MS = 3_000L
    }
}
