package tech.enlightenedrepublic.caelza.body

import android.content.Context
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationManagerCompat

/**
 * The notification feed (`sensors_notifications`, design §4): Android binds
 * this once the owner turns on notification access for Caelza in Settings,
 * and from then on the Body reads the status bar through it. Nothing is
 * stored: the Body asks for the current notifications when a tool call needs
 * them. Not enabled, or not bound yet, are the tool's `needs ...` answers.
 */
class CaelzaNotificationListener : NotificationListenerService() {
    override fun onListenerConnected() {
        instance = this
    }

    override fun onListenerDisconnected() {
        if (instance === this) instance = null
    }

    override fun onDestroy() {
        if (instance === this) instance = null
        super.onDestroy()
    }

    companion object {
        @Volatile
        private var instance: CaelzaNotificationListener? = null

        /** Did the owner turn on notification access for this app? */
        fun enabled(context: Context): Boolean =
            NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)

        /** The status bar right now, or null while Android has not bound the listener. */
        fun snapshot(): List<StatusBarNotification>? = try {
            instance?.activeNotifications?.toList()
        } catch (_: Exception) {
            null
        }

        const val WHERE = "Settings › Notifications › Notification access (or Special app access) › Caelza"
    }
}
