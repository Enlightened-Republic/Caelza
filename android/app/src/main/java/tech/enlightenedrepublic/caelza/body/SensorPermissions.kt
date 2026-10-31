package tech.enlightenedrepublic.caelza.body

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.provider.Settings
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat

/**
 * The runtime permissions the sensors need, in the owner's words. A missing
 * one degrades the tool that needs it (`error: needs the camera permission:
 * ...`), and the strip offers to ask for all of them at once; the Cael-led
 * first run (M7d) will ask for each with its reason.
 */
object SensorPermissions {
    const val REQUEST_CODE = 7301
    const val WHERE = "Settings › Apps › Caelza › Permissions"

    /** Runtime permissions, by the sensor they unlock. */
    val RUNTIME: Map<String, String> = linkedMapOf(
        "camera" to Manifest.permission.CAMERA,
        "microphone" to Manifest.permission.RECORD_AUDIO,
        "location" to Manifest.permission.ACCESS_FINE_LOCATION,
    )

    fun granted(context: Context, permission: String): Boolean =
        ContextCompat.checkSelfPermission(context, permission) == PackageManager.PERMISSION_GRANTED

    /** The sensors that cannot answer yet: `camera`, `microphone`, `location`, `notifications`. */
    fun missing(context: Context): List<String> {
        val out = RUNTIME.filter { (_, perm) -> !granted(context, perm) }.keys.toMutableList()
        if (!CaelzaNotificationListener.enabled(context)) out += "notifications"
        return out
    }

    /**
     * Ask for what is missing: the runtime permissions through the system
     * prompt, notification access through its Settings page (Android has no
     * prompt for it). True when something was asked.
     */
    fun request(activity: Activity): Boolean {
        val runtime = RUNTIME.values.filter { !granted(activity, it) }
        if (runtime.isNotEmpty()) {
            ActivityCompat.requestPermissions(activity, runtime.toTypedArray(), REQUEST_CODE)
            return true
        }
        if (!CaelzaNotificationListener.enabled(activity)) {
            try {
                activity.startActivity(Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
                return true
            } catch (_: Exception) {
                return false
            }
        }
        return false
    }

    /** `needs the camera permission: Settings › ...`, the tool's answer and the strip's line. */
    fun needs(sensor: String): String =
        if (sensor == "notifications") "needs notification access: ${CaelzaNotificationListener.WHERE}"
        else "needs the $sensor permission: $WHERE › ${sensor.replaceFirstChar { it.uppercase() }}"
}
