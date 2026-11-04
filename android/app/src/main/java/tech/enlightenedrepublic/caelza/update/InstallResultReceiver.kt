package tech.enlightenedrepublic.caelza.update

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.util.Log
import android.widget.Toast

/**
 * Where the system installer answers. First it asks for the owner's confirmation (a system
 * dialog we launch); then it reports success (the app is replaced and restarts, so this rarely
 * runs) or a failure, which we show in plain words. A signature mismatch is the likely one:
 * the installed app was signed with a different key than the update.
 */
class InstallResultReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val status = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE)
        val detail = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE).orEmpty()
        when (status) {
            PackageInstaller.STATUS_PENDING_USER_ACTION -> {
                @Suppress("DEPRECATION")
                val confirm = intent.getParcelableExtra<Intent>(Intent.EXTRA_INTENT)
                if (confirm != null) context.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
            PackageInstaller.STATUS_SUCCESS -> Log.i(TAG, "update installed")
            else -> {
                Log.w(TAG, "update failed: status=$status $detail")
                Toast.makeText(context, failureMessage(status, detail), Toast.LENGTH_LONG).show()
            }
        }
    }

    companion object {
        private const val TAG = "CaelzaUpdate"

        fun failureMessage(status: Int, detail: String): String = when {
            status == PackageInstaller.STATUS_FAILURE_ABORTED -> "Update cancelled."
            status == PackageInstaller.STATUS_FAILURE_CONFLICT || detail.contains("signature", ignoreCase = true) ->
                "This copy of Caelza was signed with a different key, so it cannot update in place. Uninstall it once and install the latest from the Releases page."
            status == PackageInstaller.STATUS_FAILURE_STORAGE -> "Not enough storage to install the update."
            else -> "The update did not install. $detail".trim()
        }
    }
}
