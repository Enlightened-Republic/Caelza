package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** A phone's sensors with canned answers in `termux-api`'s shapes; `unavailable` names what the owner has not granted. */
class FakeSensors : Sensors {
    val calls = mutableListOf<String>()
    val unavailable = mutableSetOf<String>()
    var clipboard = "hello from the clipboard"
    var approxAnswer: JSONObject = JSONObject().put("city", "Lisbon").put("region", "Lisboa").put("country", "Portugal").put("isp", "MEO")

    private fun gate(sensor: String) {
        if (sensor in unavailable) throw SensorUnavailable(NEEDS.getValue(sensor))
    }

    override fun battery(): JSONObject = JSONObject()
        .put("health", "GOOD").put("percentage", 87).put("plugged", "PLUGGED_USB")
        .put("status", "CHARGING").put("temperature", 28.5).put("current", 500000)

    override fun notifications(): JSONArray {
        gate("notifications")
        return JSONArray().put(
            JSONObject().put("id", 7).put("tag", JSONObject.NULL).put("key", "0|com.example.messages|7|null|10234")
                .put("group", JSONObject.NULL).put("packageName", "com.example.messages")
                .put("title", "Ana").put("content", "On my way").put("when", "2026-10-30 14:15:00"),
        )
    }

    override fun clipboardGet(): String {
        gate("clipboard")
        calls += "clipboard_get"
        return clipboard
    }

    override fun clipboardSet(text: String) {
        gate("clipboard")
        calls += "clipboard_set:$text"
        clipboard = text
    }

    override fun location(provider: String): JSONObject {
        gate("location")
        calls += "location:$provider"
        return JSONObject().put("latitude", 38.7223).put("longitude", -9.1393).put("altitude", 30.0).put("accuracy", 12.0)
            .put("vertical_accuracy", 4.0).put("bearing", 0.0).put("speed", 0.0).put("elapsedMs", 1200).put("provider", provider)
    }

    override fun wifi(): JSONObject = JSONObject().put("ssid", "HomeNet").put("bssid", "aa:bb:cc:dd:ee:ff").put("rssi", -55)
        .put("link_speed_mbps", 433).put("frequency_mhz", 5180).put("ip", "192.168.1.23").put("network_id", 3)
        .put("ssid_hidden", false).put("supplicant_state", "COMPLETED")

    override fun approx(): JSONObject = approxAnswer

    override fun cameraPhoto(facing: String, into: File) {
        gate("camera")
        calls += "camera:$facing"
        into.writeBytes(JPEG)
    }

    override fun micRecord(seconds: Int, into: File) {
        gate("microphone")
        calls += "mic:$seconds"
        into.writeBytes(M4A)
    }

    override fun ttsSpeak(text: String) {
        gate("tts")
        calls += "tts:$text"
    }

    override fun torch(on: Boolean) {
        gate("torch")
        calls += "torch:$on"
    }

    companion object {
        val NEEDS = mapOf(
            "camera" to "needs the camera permission: Settings › Apps › Caelza › Permissions › Camera",
            "microphone" to "needs the microphone permission: Settings › Apps › Caelza › Permissions › Microphone",
            "location" to "needs the location permission: Settings › Apps › Caelza › Permissions › Location",
            "notifications" to "needs notification access: Settings › Notifications › Notification access (or Special app access) › Caelza",
            "clipboard" to "the clipboard is empty, or Caelza is not on screen: from Android 10 only the app in front may read it; open Caelza and try again",
            "tts" to "this phone has no working text-to-speech engine",
            "torch" to "this phone has no flashlight",
        )
        val JPEG: ByteArray = byteArrayOf(0xFF.toByte(), 0xD8.toByte(), 0xFF.toByte(), 0xE0.toByte()) + "fake-jpeg".toByteArray()
        val M4A: ByteArray = byteArrayOf(0, 0, 0, 0x18, 'f'.code.toByte(), 't'.code.toByte(), 'y'.code.toByte(), 'p'.code.toByte())
    }
}
