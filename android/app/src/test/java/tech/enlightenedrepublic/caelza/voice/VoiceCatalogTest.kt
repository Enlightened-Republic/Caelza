package tech.enlightenedrepublic.caelza.voice

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phone's voices as the dashboard's offer: the best first, names once, capped, picked by name. */
class VoiceCatalogTest {
    private val voices = listOf(
        PhoneVoice("en-us-x-iom-network", "en-US", 400, true),
        PhoneVoice("en-us-x-iom-local", "en-US", 400, false),
        PhoneVoice("en-gb-x-gba-local", "en-GB", 300, false),
        PhoneVoice("en-us-x-iom-local", "en-US", 400, false),
    )

    @Test
    fun local_and_better_voices_come_first_and_names_are_unique() {
        assertEquals(listOf("en-us-x-iom-local", "en-gb-x-gba-local", "en-us-x-iom-network"), VoiceCatalog.sorted(voices).map { it.name })
    }

    @Test
    fun the_offer_is_what_the_gateway_takes() {
        val arr = JSONArray(VoiceCatalog.json(voices))
        assertEquals(3, arr.length())
        val first = arr.getJSONObject(0)
        assertEquals("en-us-x-iom-local", first.getString("id"))
        assertEquals("en-US · en-us-x-iom-local", first.getString("name"))
        assertEquals("en-US", first.getString("lang"))
        assertTrue(arr.getJSONObject(2).getString("name").endsWith("(online)"))
        assertEquals("[]", VoiceCatalog.json(emptyList()))
    }

    @Test
    fun the_offer_is_capped() {
        val many = (0 until VoiceCatalog.MAX + 50).map { PhoneVoice("v$it", "en-US", 100, false) }
        assertEquals(VoiceCatalog.MAX, JSONArray(VoiceCatalog.json(many)).length())
    }

    @Test
    fun pick_is_by_name_and_blank_means_the_default() {
        assertEquals("en-GB", VoiceCatalog.pick(voices, "en-gb-x-gba-local")?.lang)
        assertNull(VoiceCatalog.pick(voices, ""))
        assertNull(VoiceCatalog.pick(voices, null))
        assertNull(VoiceCatalog.pick(voices, "nope"))
    }
}
