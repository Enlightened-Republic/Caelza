package tech.enlightenedrepublic.caelza

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

/** The app: one notification channel for the Runtime's foreground service. */
class CaelzaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            RuntimeService.CHANNEL_ID,
            getString(R.string.runtime_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = getString(R.string.runtime_channel_description) }
        manager.createNotificationChannel(channel)
    }
}
