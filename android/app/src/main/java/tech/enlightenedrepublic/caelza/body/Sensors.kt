package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * What the phone can sense, as the Body's `sensors_*` tools need it
 * (`caelza_body/agent/tools/sensors.py`). On a Termux phone each of these is
 * a `termux-*` command; in the app [AndroidSensors] is the normal Android API
 * behind the same answers (the same JSON shapes `termux-api` prints, which the
 * dashboard's Bodies page already reads). A capability the owner has not
 * granted throws [SensorUnavailable] with what to do, and the tool answers
 * `error: needs ...`: a degraded Body, never a crash.
 */
interface Sensors {
    /** `termux-battery-status`: health, percentage, plugged, status, temperature, current. */
    fun battery(): JSONObject

    /** `termux-notification-list`: id, tag, key, group, packageName, title, content, when. */
    fun notifications(): JSONArray

    fun clipboardGet(): String

    fun clipboardSet(text: String)

    /** `termux-location -p <provider>`: latitude, longitude, altitude, accuracy, bearing, speed, elapsedMs, provider. */
    fun location(provider: String): JSONObject

    /** `termux-wifi-connectioninfo`: ssid, bssid, rssi, link_speed_mbps, frequency_mhz, ip, ... */
    fun wifi(): JSONObject

    /** City-level whereabouts from the public IP, keyless; `{}` when nothing answers. */
    fun approx(): JSONObject = IpGeo.lookup()

    /** A JPEG from the `back` or `front` camera, written to `into`. */
    fun cameraPhoto(facing: String, into: File)

    /** `seconds` of microphone audio as .m4a, written to `into`; blocks for the duration. */
    fun micRecord(seconds: Int, into: File)

    /** Speak and return once spoken. */
    fun ttsSpeak(text: String)

    fun torch(on: Boolean)
}

class SensorUnavailable(message: String) : Exception(message)

/** `sensors._ipgeo`: an approximate location from the public IP, two keyless services, `{}` on failure. */
object IpGeo {
    private class Service(val url: String, val keys: Map<String, String>)

    private val SERVICES = listOf(
        Service(
            "https://ipwho.is/",
            mapOf("city" to "city", "region" to "region", "country" to "country", "latitude" to "latitude", "longitude" to "longitude"),
        ),
        Service(
            "https://ipapi.co/json/",
            mapOf("city" to "city", "region" to "region", "country" to "country_name", "latitude" to "latitude", "longitude" to "longitude"),
        ),
    )

    const val TIMEOUT_MS = 8_000

    /** GET `url` as text, or null when it fails or answers 4xx/5xx. */
    fun fetch(url: String): String? = try {
        val conn = URL(url).openConnection() as HttpURLConnection
        conn.connectTimeout = TIMEOUT_MS
        conn.readTimeout = TIMEOUT_MS
        conn.setRequestProperty("Accept", "application/json")
        conn.setRequestProperty("User-Agent", "caelza-body/${BodyServer.SERVER_VERSION}")
        val text = if (conn.responseCode in 200..399) conn.inputStream.bufferedReader().readText() else null
        conn.disconnect()
        text
    } catch (_: Exception) {
        null
    }

    fun lookup(fetch: (String) -> String? = ::fetch): JSONObject {
        for (service in SERVICES) {
            val text = fetch(service.url) ?: continue
            val d = try {
                JSONObject(text)
            } catch (_: Exception) {
                continue
            }
            if (d.optBoolean("success", true).not()) continue
            // ipapi.co signals its rate limit as {"error": true, "reason": "RateLimited"}
            if (d.optBoolean("error", false) || d.optString("reason") == "RateLimited") continue
            val out = JSONObject()
            for ((key, src) in service.keys) if (d.has(src) && !d.isNull(src)) out.put(key, d.get(src))
            val isp = d.optJSONObject("connection")?.optString("isp")?.takeIf { it.isNotEmpty() }
                ?: d.optString("org").takeIf { it.isNotEmpty() }
            if (isp != null) out.put("isp", isp)
            if (out.has("city") || out.has("latitude")) return out
        }
        return JSONObject()
    }
}
