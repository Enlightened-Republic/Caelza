package tech.enlightenedrepublic.caelza.model

import org.apache.commons.compress.archivers.tar.TarArchiveEntry
import org.apache.commons.compress.archivers.tar.TarArchiveOutputStream
import org.apache.commons.compress.compressors.gzip.GzipCompressorOutputStream
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.ByteArrayOutputStream
import java.io.File

/** llama.cpp's Android build, pulled and laid out beside the Runtime's versions. */
class LlamaRuntimeTest {
    @get:Rule
    val tmp = TemporaryFolder()

    /** The archive the way llama.cpp's release packs it: everything flat under `llama-<tag>/`. */
    private fun archive(tag: String): ByteArray {
        val out = ByteArrayOutputStream()
        TarArchiveOutputStream(GzipCompressorOutputStream(out)).use { tar ->
            fun add(path: String, content: String, mode: Int) {
                val bytes = content.toByteArray()
                tar.putArchiveEntry(TarArchiveEntry(path).apply { size = bytes.size.toLong(); this.mode = mode })
                tar.write(bytes)
                tar.closeArchiveEntry()
            }
            add("llama-$tag/llama-server", "#!/bin/sh\necho fake llama-server\n", 0b111_101_101)
            add("llama-$tag/libllama.so", "not really a library", 0b110_100_100)
            add("llama-$tag/libggml-cpu-android_armv8.2_1.so", "variant", 0b110_100_100)
            add("llama-$tag/LICENSE", "MIT\n", 0b110_100_100)
        }
        return out.toByteArray()
    }

    @Test
    fun install_pulls_the_pinned_build_lays_it_out_and_points_current_at_it() {
        val bytes = archive("b11960")
        val pin = LlamaPin("b11960", sha256Hex(bytes), bytes.size.toLong())
        assertEquals("llama-b11960-bin-android-arm64.tar.gz", pin.asset)
        assertEquals("https://github.com/ggml-org/llama.cpp/releases/download/b11960/llama-b11960-bin-android-arm64.tar.gz", pin.url)
        val llama = LlamaRuntime(tmp.root)
        assertFalse(llama.installed)
        val dl = FakeDownloader(bytes)
        val server = llama.install(dl, pin = pin)
        assertEquals(File(tmp.root, "runtime/llama/b11960/llama-server"), server)
        assertTrue(server.isFile && server.canExecute())
        assertTrue(File(server.parentFile, "libllama.so").isFile)
        assertEquals("b11960", llama.current)
        assertTrue(llama.installed)
        assertEquals(server, llama.currentServer)
        assertFalse(File(tmp.root, "tmp").listFiles().orEmpty().any { it.name.startsWith("llama-install") })
        // Installed already: no second download.
        llama.install(dl, pin = pin)
        assertEquals(listOf(0L), dl.opens)
    }

    @Test
    fun a_tampered_archive_is_refused_before_anything_is_laid_out() {
        val bytes = archive("b11960")
        val pin = LlamaPin("b11960", "0".repeat(64), bytes.size.toLong())
        val llama = LlamaRuntime(tmp.root)
        try {
            llama.install(FakeDownloader(bytes), pin = pin)
            throw AssertionError("expected a checksum mismatch")
        } catch (e: IllegalStateException) {
            assertTrue(e.message!!.contains("checksum mismatch"))
        }
        assertFalse(llama.installed)
        assertNull(llama.current)
    }

    @Test
    fun prune_keeps_only_the_current_tag_and_the_command_is_serve_shs() {
        val llama = LlamaRuntime(tmp.root)
        for (tag in listOf("b11000", "b11960")) {
            val bytes = archive(tag)
            llama.install(FakeDownloader(bytes), pin = LlamaPin(tag, sha256Hex(bytes), bytes.size.toLong()))
        }
        assertEquals("b11960", llama.current)
        assertEquals(listOf("b11000"), llama.prune())
        assertTrue(llama.server("b11960").isFile && !llama.server("b11000").exists())
        val cmd = LlamaRuntime.command(llama.currentServer!!, File("/m/x.gguf"), threads = 4)
        assertEquals(listOf(llama.currentServer!!.path, "-m", "/m/x.gguf", "--host", "127.0.0.1", "--port", "8080", "-c", "4096", "--threads", "4"), cmd)
        assertTrue(LlamaRuntime.cpuThreads() >= 1)
        assertEquals("b11960", LlamaPin.CURRENT.tag)
        assertEquals(64, LlamaPin.CURRENT.sha256.length)
    }
}
