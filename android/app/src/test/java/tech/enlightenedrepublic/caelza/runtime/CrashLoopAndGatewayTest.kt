package tech.enlightenedrepublic.caelza.runtime

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.net.ServerSocket

class CrashLoopAndGatewayTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun three_exits_inside_the_window_trip_the_loop_and_old_ones_fall_out() {
        val loop = CrashLoop(n = 3, windowMs = 300_000)
        loop.recordExit(0)
        loop.recordExit(1_000)
        assertFalse(loop.tripped(2_000))
        loop.recordExit(2_000)
        assertTrue(loop.tripped(2_000))
        assertFalse("the first two exits have aged out", loop.tripped(400_000))
        loop.reset()
        loop.recordExit(500_000)
        assertFalse(loop.tripped(500_000))
    }

    @Test
    fun the_gateway_port_comes_from_the_gateway_section_only() {
        val cfg = File(tmp.root, ".caelza").apply { mkdirs() }
        assertEquals(RuntimeStore.GATEWAY_PORT, Gateway.port(cfg))
        File(cfg, "config.toml").writeText("schema_version = 3\n\n[channels.telegram.home]\nport = 1\n\n[gateway]\nhost = \"127.0.0.1\"\nport = 4242\n\n[other]\nport = 9\n")
        assertEquals(4242, Gateway.port(cfg))
        File(cfg, "config.toml").writeText("[gateway]\nhost = \"127.0.0.1\"\n")
        assertEquals(RuntimeStore.GATEWAY_PORT, Gateway.port(cfg))
        assertEquals("http://127.0.0.1:4242/health", Gateway.url(4242, "/health"))
    }

    @Test
    fun a_closed_port_is_not_healthy() {
        val port = ServerSocket(0).use { it.localPort }
        assertFalse(Gateway.healthy(port, 500))
    }
}
