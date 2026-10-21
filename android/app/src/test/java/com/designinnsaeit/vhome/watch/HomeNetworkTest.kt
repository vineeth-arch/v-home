package com.designinnsaeit.vhome.watch

import org.junit.Assert.assertEquals
import org.junit.Test

class HomeNetworkTest {
    @Test fun pairingSavesKeyAndPin() {
        val old = Config(vhomeId = "my.vhome", homeIds = listOf("a", "b"), paused = true)
        val c = applyPairing(old, "192.168.1.20", "KEY", "PIN")
        assertEquals("192.168.1.20", c.host)
        assertEquals("KEY", c.clientKey)
        assertEquals("PIN", c.pin)
        assertEquals("my.vhome", c.vhomeId)
        assertEquals(listOf("a", "b"), c.homeIds)
        assertEquals(true, c.paused)
    }

    @Test fun pairingOverwritesOldHost() {
        val old = Config(host = "10.0.0.1", clientKey = "OLD", pin = "OLDPIN")
        val c = applyPairing(old, "10.0.0.2", "NEW", "NEWPIN")
        assertEquals(Config(host = "10.0.0.2", clientKey = "NEW", pin = "NEWPIN"), c)
    }
}
