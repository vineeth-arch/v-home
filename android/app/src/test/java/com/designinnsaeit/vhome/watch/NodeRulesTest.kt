package com.designinnsaeit.vhome.watch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeRulesTest {
    @Test fun freshIsNotStale() {
        assertFalse(NodeRules.isStale(fetchedAtElapsed = 1_000, nowElapsed = 3_000, ageS = 2.0))
    }

    @Test fun oldNodeAgeIsStale() {
        assertTrue(NodeRules.isStale(1_000, 1_000, ageS = 25.0))
    }

    @Test fun phoneSideTimePassingMakesItStale() {
        assertFalse(NodeRules.isStale(0, 5_000, 1.0))
        assertTrue(NodeRules.isStale(0, 25_000, 1.0))
    }

    @Test fun neverObservedIsStale() {
        assertTrue(NodeRules.isStale(0, 0, null))
        assertNull(NodeRules.observedAgeMs(0, 0, null))
    }

    @Test fun observedAgeAddsPhoneElapsedToNodeAge() {
        assertEquals(4_500L, NodeRules.observedAgeMs(10_000, 12_000, 2.5))
    }

    @Test fun observedAgeNeverGoesNegative() {
        assertEquals(1_000L, NodeRules.observedAgeMs(10_000, 5_000, 1.0))
    }

    @Test fun switchToStandaloneTruthTable() {
        assertTrue(NodeRules.canSwitchToStandalone(true, false))
        assertTrue(NodeRules.canSwitchToStandalone(false, true))
        assertTrue(NodeRules.canSwitchToStandalone(true, true))
        assertFalse(NodeRules.canSwitchToStandalone(false, false))
    }

    @Test fun fingerprintIsSixGroupsOfFour() {
        val id = "3F9A1C2E88B07D4102AA9C11FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF"
        assertEquals("3f9a 1c2e 88b0 7d41 02aa 9c11", NodeRules.fingerprintGroups(id))
    }
}
