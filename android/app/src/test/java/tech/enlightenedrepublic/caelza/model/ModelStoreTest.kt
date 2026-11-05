package tech.enlightenedrepublic.caelza.model

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayInputStream
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.security.MessageDigest

/** A server with one file: honours `Range`, can cut the stream once, can ignore the range, can serve the wrong bytes. */
class FakeDownloader(private val bytes: ByteArray, private val cutAfter: Int = -1, private val honourRange: Boolean = true) : Downloader {
    val opens = mutableListOf<Long>()
    private var cuts = 0

    override fun open(url: String, from: Long): Download {
        opens += from
        val start = if (honourRange) from.toInt() else 0
        var slice = bytes.copyOfRange(start, bytes.size)
        val cut = cutAfter >= 0 && cuts == 0 && slice.size > cutAfter
        if (cut) {
            cuts++
            slice = slice.copyOfRange(0, cutAfter)
        }
        val stream: InputStream = if (cut) CutStream(slice) else ByteArrayInputStream(slice)
        return Download(stream, resumed = honourRange && from > 0, total = bytes.size.toLong())
    }

    /** The bytes, then a dropped connection. */
    private class CutStream(data: ByteArray) : InputStream() {
        private val inner = ByteArrayInputStream(data)
        override fun read(): Int = inner.read().also { if (it < 0) throw IOException("connection reset") }
        override fun read(b: ByteArray, off: Int, len: Int): Int = inner.read(b, off, len).also { if (it < 0) throw IOException("connection reset") }
    }
}

fun sha256Hex(bytes: ByteArray): String = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }

class ModelStoreTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val payload = ByteArray(300_000) { (it * 31 % 251).toByte() }
    private val gguf = ModelLadder.Gguf("test", "Tiny-Test-Q4", "Tiny-Test-Q4.gguf", "test/Tiny-GGUF", sha256Hex(payload), payload.size.toLong())

    private fun store() = ModelStore(File(tmp.root, "models"))

    @Test
    fun a_download_is_verified_marked_and_not_fetched_twice() {
        val s = store()
        val dl = FakeDownloader(payload)
        val seen = mutableListOf<Pair<Long, Long>>()
        val file = s.download(gguf, dl) { done, total -> seen += done to total }
        assertTrue(file.isFile && file.readBytes().contentEquals(payload))
        assertTrue(s.verified(gguf))
        assertEquals(payload.size.toLong(), seen.last().first)
        assertEquals(listOf(0L), dl.opens)
        assertFalse(File(s.dir, gguf.file + ".part").exists())
        s.download(gguf, dl)
        assertEquals("already verified: no second fetch", listOf(0L), dl.opens)
    }

    @Test
    fun a_cut_connection_resumes_from_the_part_file_and_still_verifies() {
        val s = store()
        val dl = FakeDownloader(payload, cutAfter = 120_000)
        val file = s.download(gguf, dl)
        assertTrue(file.readBytes().contentEquals(payload))
        assertEquals(listOf(0L, 120_000L), dl.opens)
        assertTrue(s.verified(gguf))
    }

    @Test
    fun a_server_that_ignores_the_range_starts_over_and_the_hash_is_still_right() {
        val s = store()
        File(s.dir, gguf.file + ".part").apply { parentFile!!.mkdirs(); writeBytes(payload.copyOfRange(0, 1000)) }
        val dl = FakeDownloader(payload, honourRange = false)
        assertTrue(s.download(gguf, dl).readBytes().contentEquals(payload))
        assertEquals(listOf(1000L), dl.opens)
        assertTrue(s.verified(gguf))
    }

    @Test
    fun a_part_that_is_already_whole_is_verified_without_a_request() {
        // The process died between the last write and the rename: no range past the end (a 416 that nothing could clear).
        val s = store()
        File(s.dir, gguf.file + ".part").apply { parentFile!!.mkdirs(); writeBytes(payload) }
        val dl = FakeDownloader(payload)
        assertTrue(s.download(gguf, dl).readBytes().contentEquals(payload))
        assertEquals(emptyList<Long>(), dl.opens)
        assertTrue(s.verified(gguf))
        assertFalse(File(s.dir, gguf.file + ".part").exists())
    }

    @Test
    fun a_whole_part_with_the_wrong_bytes_is_thrown_away_and_fetched_again() {
        val s = store()
        val wrong = payload.copyOf().also { it[7] = (it[7] + 1).toByte() }
        File(s.dir, gguf.file + ".part").apply { parentFile!!.mkdirs(); writeBytes(wrong) }
        val dl = FakeDownloader(payload)
        assertTrue(s.download(gguf, dl).readBytes().contentEquals(payload))
        assertEquals("from the start", listOf(0L), dl.opens)
        assertTrue(s.verified(gguf))
    }

    @Test
    fun tampered_bytes_are_refused_and_nothing_is_kept() {
        val s = store()
        val wrong = payload.copyOf().also { it[7] = (it[7] + 1).toByte() }
        val e = assertThrows(IllegalStateException::class.java) { s.download(gguf, FakeDownloader(wrong)) }
        assertTrue(e.message!!.contains("checksum mismatch"))
        assertFalse(s.file(gguf).exists())
        assertFalse(File(s.dir, gguf.file + ".part").exists())
        assertFalse(s.verified(gguf))
    }

    @Test
    fun a_server_whose_size_disagrees_with_the_pin_is_refused_before_the_first_byte() {
        // The app once pinned the 1.5B at 64 bytes under its real size: every attempt downloaded the
        // whole gigabyte, threw it away as "short" and started over, five times, then gave up.
        val s = store()
        val stale = gguf.copy(bytes = payload.size.toLong() - 64)
        val dl = FakeDownloader(payload)
        val e = assertThrows(IllegalStateException::class.java) { s.download(stale, dl) }
        assertTrue(e.message, e.message!!.contains("the server says ${payload.size} bytes") && e.message!!.contains("pin says ${payload.size - 64}"))
        assertEquals("one request, no retries", listOf(0L), dl.opens)
        assertFalse(s.file(stale).exists())
        assertFalse(s.verified(stale))
    }

    @Test
    fun more_bytes_than_pinned_from_a_server_that_names_no_size_is_a_stale_pin_not_a_retry() {
        val s = store()
        val stale = gguf.copy(bytes = payload.size.toLong() - 64)
        var opens = 0
        val silent = object : Downloader {
            override fun open(url: String, from: Long): Download {
                opens++
                return Download(ByteArrayInputStream(payload.copyOfRange(from.toInt(), payload.size)), resumed = from > 0, total = null)
            }
        }
        val e = assertThrows(IllegalStateException::class.java) { s.download(stale, silent) }
        assertTrue(e.message, e.message!!.contains("${payload.size} bytes arrived") && e.message!!.contains("pin is stale"))
        assertEquals(1, opens)
        assertFalse("the long part is not kept for a resume that could never verify", File(s.dir, stale.file + ".part").exists())
    }

    @Test
    fun a_connection_that_keeps_dropping_gives_up_after_the_attempts() {
        val always = object : Downloader {
            override fun open(url: String, from: Long): Download = Download(object : InputStream() {
                override fun read(): Int = throw IOException("no route")
            }, resumed = from > 0, total = null)
        }
        val e = assertThrows(IOException::class.java) { VerifiedDownload.fetch(gguf.url, gguf.sha256, gguf.bytes, File(tmp.root, "x.gguf"), always, attempts = 2) }
        assertEquals("no route", e.message)
    }

    @Test
    fun verified_means_the_pinned_size_and_a_marker_that_names_the_pin() {
        val s = store()
        s.dir.mkdirs()
        s.file(gguf).writeBytes(payload)
        assertFalse("no marker yet", s.verified(gguf))
        File(s.dir, gguf.file + ".sha256").writeText(gguf.sha256 + "\n")
        assertTrue(s.verified(gguf))
        s.file(gguf).writeBytes(payload.copyOfRange(0, 10))
        assertFalse("wrong size", s.verified(gguf))
    }

    @Test
    fun serve_json_names_the_model_the_server_loads() {
        val s = store()
        assertNull(s.serve())
        s.writeServe(ModelServe("Tiny-Test-Q4.gguf"))
        val serve = s.serve()!!
        assertEquals("Tiny-Test-Q4.gguf", serve.model)
        assertEquals(ModelLadder.SERVER_PORT, serve.port)
        assertEquals(ModelLadder.CONTEXT, serve.ctx)
        assertEquals(ModelServe("a.gguf", 8081, 2048), ModelServe.fromJson("""{"model":"a.gguf","port":8081,"ctx":2048}"""))
        assertNull(ModelServe.fromJson("not json"))
        s.clearServe()
        assertNull(s.serve())
    }
}
