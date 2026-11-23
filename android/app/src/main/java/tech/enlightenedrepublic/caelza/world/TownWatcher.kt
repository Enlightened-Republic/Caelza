package tech.enlightenedrepublic.caelza.world

import android.content.Context
import android.os.FileObserver
import android.util.Log
import java.io.File

/**
 * Tells the owner when the town wakes their agent (vision M10, slice 5). The
 * gateway writes `world/last-wake.json` under its config dir after every wake
 * (a temp file renamed into place); this watches that folder and hands each
 * wake newer than the last one shown to [onWake], which posts the
 * notification. The time of the last wake shown is kept in the app's
 * preferences, so a restart repeats nothing. Reads only: the file is the
 * gateway's.
 */
class TownWatcher(context: Context, private val configDir: File, private val onWake: (TownWake) -> Unit) {
    private val prefs = context.applicationContext.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private var observer: FileObserver? = null

    fun start() {
        if (observer != null) return
        val dir = TownWake.dir(configDir)
        dir.mkdirs()
        @Suppress("DEPRECATION") // the File constructor is API 29; this app runs from 28
        observer = object : FileObserver(dir.path, CLOSE_WRITE or MOVED_TO) {
            override fun onEvent(event: Int, path: String?) {
                if (path == TownWake.FILE) check()
            }
        }.also { it.startWatching() }
        // A wake that landed while the watcher was off.
        check()
    }

    fun stop() {
        observer?.stopWatching()
        observer = null
    }

    /** The file as it is now; the owner hears of it once. */
    fun check() {
        val wake = try {
            TownWake.read(configDir)
        } catch (e: Exception) {
            Log.w(TAG, "the last wake could not be read", e)
            null
        } ?: return
        if (!wake.isAfter(prefs.getLong(KEY_SHOWN_AT, 0L))) return
        prefs.edit().putLong(KEY_SHOWN_AT, wake.at).apply()
        onWake(wake)
    }

    companion object {
        private const val TAG = "TownWatcher"
        const val PREFS = "town"
        const val KEY_SHOWN_AT = "shown_at"
    }
}
