package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/**
 * The `sensors_*` tools over a fake phone: the answers in `termux-api`'s
 * shapes, the captures under tmp, the one-phone guard, what a permission not
 * granted turns into, and the IP geolocation's two services.
 */
class SensorToolsTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private lateinit var sensors: FakeSensors
    private lateinit var home: BodyHome
    private lateinit var tools: BodyTools

    @Before
    fun setUp() {
        sensors = FakeSensors()
        home = BodyHome(File(tmp.root, ".caelza-body"))
        tools = BodyTools(BodyShell(FakeShell()), home, sensors)
    }

    private fun call(name: String, vararg args: Pair<String, Any>): BodyTools.ToolResult =
        tools.call(name, JSONObject().also { o -> for ((k, v) in args) o.put(k, v) })

    private fun json(name: String, vararg args: Pair<String, Any>): JSONObject {
        val out = call(name, *args)
        assertTrue(out.text, out.text.startsWith("{"))
        return JSONObject(out.text)
    }

    @Test
    fun battery_and_notifications_answer_in_termux_apis_shapes() {
        val battery = json("sensors_battery")
        assertEquals(87, battery.getInt("percentage"))
        assertEquals("CHARGING", battery.getString("status"))
        assertEquals("PLUGGED_USB", battery.getString("plugged"))
        assertEquals(28.5, battery.getDouble("temperature"), 0.0)
        val out = call("sensors_notifications")
        val list = JSONArray(out.text)
        assertEquals(1, list.length())
        assertEquals("Ana", list.getJSONObject(0).getString("title"))
        assertEquals("com.example.messages", list.getJSONObject(0).getString("packageName"))
        assertEquals("2026-10-30 14:15:00", list.getJSONObject(0).getString("when"))
    }

    @Test
    fun the_clipboard_reads_and_writes() {
        assertEquals("hello from the clipboard", call("sensors_clipboard_get").text)
        assertEquals("set", call("sensors_clipboard_set", "text" to "a note from Cael").text)
        assertEquals("a note from Cael", sensors.clipboard)
        assertEquals(listOf("clipboard_get", "clipboard_set:a note from Cael"), sensors.calls)
    }

    @Test
    fun location_quick_is_wifi_plus_a_city_and_the_other_modes_are_coordinates() {
        val quick = json("sensors_location")
        assertEquals("HomeNet", quick.getJSONObject("wifi").getString("ssid"))
        assertEquals("Lisbon", quick.getJSONObject("approx").getString("city"))
        assertEquals("approx is city-level from the IP; call with mode='gps' for coordinates", quick.getString("note"))
        assertTrue(sensors.calls.isEmpty())
        assertEquals("gps", json("sensors_location", "mode" to "gps").getString("provider"))
        assertEquals("network", json("sensors_location", "mode" to "quick", "accuracy" to "coarse").getString("provider"))
        assertEquals("gps", json("sensors_location", "accuracy" to "fine").getString("provider"))
        assertEquals(listOf("location:gps", "location:network", "location:gps"), sensors.calls)
    }

    @Test
    fun a_photo_lands_under_tmp_and_comes_back_as_a_jpeg() {
        val out = call("sensors_camera_photo")
        assertEquals("photo captured", out.text)
        val (file, mime) = out.images.single()
        assertEquals("image/jpeg", mime)
        assertTrue(file.path, file.parentFile == home.tmp && file.name.startsWith("cam-") && file.name.endsWith(".jpg"))
        assertTrue(file.readBytes().contentEquals(FakeSensors.JPEG))
        call("sensors_camera_photo", "facing" to "front")
        assertEquals(listOf("camera:back", "camera:front"), sensors.calls)
    }

    @Test
    fun a_recording_is_its_path_and_the_seconds_are_clamped() {
        val path = call("sensors_mic_record").text
        assertTrue(path, path.startsWith(home.tmp.path) && path.endsWith(".m4a") && File(path).isFile)
        call("sensors_mic_record", "seconds" to 0)
        call("sensors_mic_record", "seconds" to 600)
        assertEquals(listOf("mic:8", "mic:1", "mic:60"), sensors.calls)
    }

    @Test
    fun speaking_and_the_torch_answer_as_the_python_body_does() {
        assertEquals("spoken", call("sensors_tts_speak", "text" to "Hello, I am Cael").text)
        assertEquals("torch on", call("sensors_torch").text)
        assertEquals("torch off", call("sensors_torch", "on" to false).text)
        assertEquals(listOf("tts:Hello, I am Cael", "torch:true", "torch:false"), sensors.calls)
        assertTrue(call("sensors_tts_speak").text.startsWith("error: input validation: 'text' is a required property"))
    }

    @Test
    fun a_sensor_is_this_phones_own() {
        assertEquals(
            "error: sensors_battery is a sensor of this phone; 'grandma' answers only as a joined Body (device_join), not as an ADB-paired phone",
            call("sensors_battery", "device" to "grandma").text,
        )
        assertEquals("spoken", call("sensors_tts_speak", "text" to "hi", "device" to "self").text)
    }

    @Test
    fun what_the_owner_has_not_granted_is_an_answer_not_a_crash() {
        sensors.unavailable += setOf("camera", "notifications", "location", "microphone")
        val shot = call("sensors_camera_photo")
        assertEquals("error: needs the camera permission: Settings › Apps › Caelza › Permissions › Camera", shot.text)
        assertTrue(shot.isError && shot.images.isEmpty())
        assertTrue(home.tmp.listFiles().orEmpty().none { it.name.startsWith("cam-") && it.length() > 0 })
        assertEquals("error: needs notification access: Settings › Notifications › Notification access (or Special app access) › Caelza", call("sensors_notifications").text)
        assertTrue(call("sensors_location", "mode" to "gps").text.startsWith("error: needs the location permission"))
        assertTrue(call("sensors_mic_record", "seconds" to 2).text.startsWith("error: needs the microphone permission"))
        // quick mode needs no permission: wifi and the IP are enough.
        assertEquals("Lisbon", json("sensors_location").getJSONObject("approx").getString("city"))
        // battery needs none either.
        assertEquals(87, json("sensors_battery").getInt("percentage"))
    }

    @Test
    fun the_sensors_are_classified_as_the_python_body_classifies_them() {
        for (name in listOf("sensors_battery", "sensors_notifications", "sensors_clipboard_get", "sensors_location")) {
            assertEquals(name, BodyTools.Safety.READ_ONLY, tools.tool(name)!!.spec.safety)
        }
        for (name in listOf("sensors_camera_photo", "sensors_mic_record", "sensors_tts_speak", "sensors_clipboard_set", "sensors_torch")) {
            assertEquals(name, BodyTools.Safety.NEUTRAL, tools.tool(name)!!.spec.safety)
        }
        for (tool in tools.tools.filter { it.name.startsWith("sensors_") }) {
            val device = JSONObject(tool.spec.schema).getJSONObject("properties").getJSONObject("device")
            assertEquals("self", device.getString("default"))
            assertTrue(tool.name, device.getString("description").startsWith("`self` (this phone)"))
        }
        assertEquals(25, BodyTools.SPECS.size)
    }

    @Test
    fun the_ip_geolocation_tries_both_services_and_skips_refusals() {
        val answers = mutableMapOf<String, String?>()
        val fetch: (String) -> String? = { url -> answers[url] }
        assertEquals(0, IpGeo.lookup(fetch).length())
        answers["https://ipwho.is/"] = """{"success": false, "message": "limit"}"""
        answers["https://ipapi.co/json/"] = """{"city": "Porto", "region": "Porto", "country_name": "Portugal", "latitude": 41.15, "longitude": -8.61, "org": "NOS"}"""
        val second = IpGeo.lookup(fetch)
        assertEquals("Porto", second.getString("city"))
        assertEquals("Portugal", second.getString("country"))
        assertEquals("NOS", second.getString("isp"))
        answers["https://ipwho.is/"] = """{"success": true, "city": "Lisbon", "region": "Lisboa", "country": "Portugal", "latitude": 38.7, "longitude": -9.1, "connection": {"isp": "MEO"}}"""
        val first = IpGeo.lookup(fetch)
        assertEquals("Lisbon", first.getString("city"))
        assertEquals("MEO", first.getString("isp"))
        answers["https://ipwho.is/"] = "not json"
        answers["https://ipapi.co/json/"] = """{"error": true, "reason": "RateLimited"}"""
        assertEquals(0, IpGeo.lookup(fetch).length())
        answers["https://ipapi.co/json/"] = """{"org": "Only an ISP"}"""
        assertFalse("no city and no coordinates is no answer", IpGeo.lookup(fetch).has("isp"))
    }
}
