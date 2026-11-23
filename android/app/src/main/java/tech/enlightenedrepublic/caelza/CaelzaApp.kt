package tech.enlightenedrepublic.caelza

import android.app.Application
import android.app.NotificationChannel
import android.app.NotificationManager

/**
 * The app: two notification channels, the Runtime's foreground service (quiet)
 * and Ether Hollow (the town woke the agent; the owner may want to know).
 */
class CaelzaApp : Application() {
    override fun onCreate() {
        super.onCreate()
        val manager = getSystemService(NotificationManager::class.java)
        val runtime = NotificationChannel(
            RuntimeService.CHANNEL_ID,
            getString(R.string.runtime_channel_name),
            NotificationManager.IMPORTANCE_LOW,
        ).apply { description = getString(R.string.runtime_channel_description) }
        manager.createNotificationChannel(runtime)
        val town = NotificationChannel(
            RuntimeService.TOWN_CHANNEL_ID,
            getString(R.string.town_channel_name),
            NotificationManager.IMPORTANCE_DEFAULT,
        ).apply { description = getString(R.string.town_channel_description) }
        manager.createNotificationChannel(town)
    }
}
