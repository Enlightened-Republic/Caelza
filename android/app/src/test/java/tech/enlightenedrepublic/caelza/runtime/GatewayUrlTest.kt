package tech.enlightenedrepublic.caelza.runtime

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** The shell trusts one origin with its token: the gateway's, on loopback, on its port. */
class GatewayUrlTest {
    @Test
    fun only_the_gateways_own_origin_is_its_own() {
        assertTrue(Gateway.own(Gateway.url(42617, "/health"), 42617))
        assertTrue(Gateway.own("http://127.0.0.1:42617/", 42617))
        assertTrue(Gateway.own("http://127.0.0.1:42617/agent/main?x=1#y", 42617))
        // Another host with the same path, another port, another scheme, a userinfo trick, nothing.
        assertFalse(Gateway.own("https://evil.example/health", 42617))
        assertFalse(Gateway.own("http://evil.example/health", 42617))
        assertFalse(Gateway.own("http://127.0.0.1:42618/health", 42617))
        assertFalse(Gateway.own("http://127.0.0.1/health", 42617))
        assertFalse(Gateway.own("https://127.0.0.1:42617/health", 42617))
        assertFalse(Gateway.own("http://127.0.0.1:42617@evil.example/health", 42617))
        assertFalse("the shell always loads 127.0.0.1", Gateway.own("http://localhost:42617/health", 42617))
        assertFalse(Gateway.own("not a url", 42617))
        assertFalse(Gateway.own(null, 42617))
    }
}
