package tech.enlightenedrepublic.caelza

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore

/** After a reboot, start the Runtime again when one is installed and the owner left it on. */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (intent.action != Intent.ACTION_BOOT_COMPLETED) return
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        if (!prefs.getBoolean(KEY_START_AT_BOOT, true)) return
        if (RuntimeStore(context.filesDir).currentBinary == null) return
        RuntimeService.start(context)
    }

    companion object {
        const val PREFS = "caelza"
        const val KEY_START_AT_BOOT = "start_at_boot"
    }
}
