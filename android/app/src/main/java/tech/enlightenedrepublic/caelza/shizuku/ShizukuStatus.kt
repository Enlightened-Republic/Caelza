package tech.enlightenedrepublic.caelza.shizuku

import android.content.pm.PackageManager
import rikka.shizuku.Shizuku

/**
 * Shizuku is the privilege layer the app will use for the Body's device tools
 * (vision §3.3). This slice only reads where it stands and asks for the
 * permission; the tools come with the Body port.
 */
object ShizukuStatus {
    const val REQUEST_CODE = 7234

    enum class State { NOT_RUNNING, UNSUPPORTED, PERMISSION_NEEDED, READY }

    fun state(): State = try {
        when {
            !Shizuku.pingBinder() -> State.NOT_RUNNING
            Shizuku.isPreV11() -> State.UNSUPPORTED
            Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED -> State.READY
            else -> State.PERMISSION_NEEDED
        }
    } catch (_: Throwable) {
        State.NOT_RUNNING
    }

    /** Ask for the permission through Shizuku's own prompt when that is the missing piece. */
    fun request(): Boolean {
        if (state() != State.PERMISSION_NEEDED) return false
        return try {
            Shizuku.requestPermission(REQUEST_CODE)
            true
        } catch (_: Throwable) {
            false
        }
    }

    fun label(state: State): String = when (state) {
        State.NOT_RUNNING -> "not running (start it in the Shizuku app)"
        State.UNSUPPORTED -> "too old (needs Shizuku 11+)"
        State.PERMISSION_NEEDED -> "permission needed"
        State.READY -> "ready"
    }
}
