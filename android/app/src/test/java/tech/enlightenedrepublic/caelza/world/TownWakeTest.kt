package tech.enlightenedrepublic.caelza.world

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File

/** The gateway's last-wake file as the phone reads it, and which wakes are new. */
class TownWakeTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val saved = """{"name":"Moss","agent":"main","at":1763917500,"reason":"Ana named you on the feed: \"hi Moss\"","ok":true,"output":"NO_REPLY","count":3}"""

    @Test
    fun the_file_parses_and_the_outcome_is_in_the_cards_words() {
        val w = TownWake.parse(saved)!!
        assertEquals("Moss", w.name)
        assertEquals(1763917500L, w.at)
        assertEquals("Ana named you on the feed: \"hi Moss\"", w.reason)
        assertEquals(true, w.ok)
        assertEquals(3L, w.count)
        assertEquals("nothing needed doing", w.outcome())
        assertEquals("I replied to Ana.", TownWake.parse("""{"at":5,"reason":"r","ok":true,"output":" I replied to Ana. "}""")!!.outcome())
        assertEquals("the wake failed", TownWake.parse("""{"at":5,"reason":"r","ok":false,"output":"the job failed"}""")!!.outcome())
        assertEquals("nothing needed doing", TownWake.parse("""{"at":5,"reason":"r","ok":null}""")!!.outcome())
        assertNull(TownWake.parse("""{"at":5,"reason":"r"}""")!!.ok)
    }

    @Test
    fun what_is_not_a_wake_is_null() {
        for (bad in listOf("", "nope", "[]", """{"reason":"r"}""", """{"at":0,"reason":"r"}""", """{"at":5,"reason":"  "}""")) {
            assertNull(bad, TownWake.parse(bad))
        }
    }

    @Test
    fun only_a_newer_wake_is_told() {
        val w = TownWake.parse(saved)!!
        assertTrue(w.isAfter(0))
        assertTrue(w.isAfter(1763917499))
        assertFalse(w.isAfter(1763917500))
        assertFalse(w.isAfter(1763917501))
    }

    @Test
    fun the_file_is_read_from_the_gateways_world_folder() {
        val dir = File(tmp.newFolder(), ".caelza")
        assertNull(TownWake.read(dir))
        TownWake.file(dir).apply {
            parentFile!!.mkdirs()
            writeText(saved)
        }
        assertEquals("world/last-wake.json", TownWake.file(dir).relativeTo(dir).path)
        assertEquals("Moss", TownWake.read(dir)?.name)
        TownWake.file(dir).writeText("not json")
        assertNull(TownWake.read(dir))
    }
}
