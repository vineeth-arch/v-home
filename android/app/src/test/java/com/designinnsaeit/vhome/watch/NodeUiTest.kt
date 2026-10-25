package com.designinnsaeit.vhome.watch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeUiTest {
    private fun status(headline: String, tvAge: Double?) = NodeStatus(
        headline, "v", 1, "connected", null, null, null, tvAge, null, "idle", "", "watching", true, false, null, 0, null, null,
    )

    @Test fun staleDataNeverSaysWatching() {
        val s = status("connected", 30.0)
        val stale = NodeUi.isStale(s.headline, 0, 1_000, s.tvAgeS)
        assertTrue(stale)
        val hero = NodeUi.hero(s, stale, "21:04")
        assertEquals("Last seen 21:04", hero.title)
        assertFalse(hero.title.contains("Watching") || hero.explain.contains("Watching"))
    }

    @Test fun freshConnectedSaysWatching() {
        val s = status("connected", 1.0)
        assertFalse(NodeUi.isStale(s.headline, 0, 2_000, s.tvAgeS))
        assertEquals("Watching your TV", NodeUi.hero(s, false, "").title)
    }

    @Test fun oldFetchIsStaleWhateverTheHeadline() {
        assertTrue(NodeUi.isStale("unreachable", 0, 30_000, 0.0))
    }

    @Test fun unreachableDoesNotNeedFreshTvAge() {
        assertFalse(NodeUi.isStale("unreachable", 0, 1_000, null))
    }

    @Test fun everyHeadlineHasWords() {
        listOf("connected", "standby", "unreachable", "pairing_required", "certificate_mismatch", "permission_denied",
            "launcher_missing", "user_paused", "safety_paused", "disabled", "unknown", "something_new").forEach {
            assertTrue(NodeUi.title(it).isNotBlank())
            assertTrue(NodeUi.explain(it).isNotBlank())
        }
        assertEquals("Paused after repeated failures. Check the TV, then resume.", NodeUi.explain("safety_paused"))
    }

    @Test fun everyProblemHasAMessage() {
        NodeProblem.values().forEach { assertTrue(NodeUi.problemMessage(it).isNotBlank()) }
        assertTrue(NodeUi.problemMessage(NodeProblem.NOT_ON_WIFI, vpn = true).contains("VPN"))
        assertFalse(NodeUi.problemMessage(NodeProblem.NOT_ON_WIFI, vpn = false).contains("VPN"))
        assertNotEquals(NodeUi.problemMessage(NodeProblem.UNAUTHORIZED, pairing = true), NodeUi.problemMessage(NodeProblem.UNAUTHORIZED))
    }

    @Test fun launchOutcomesAreSpelledOut() {
        assertEquals("V/HOME is on the TV", NodeUi.launchText(CommandResult(Outcome.CONFIRMED, "")))
        assertTrue(NodeUi.launchText(CommandResult(Outcome.ACCEPTED, "")).contains("not seen in front yet"))
        assertTrue(NodeUi.launchText(CommandResult(Outcome.FAILED, "TV busy")).endsWith("TV busy"))
        assertEquals(NodeUi.UNKNOWN_RESULT, NodeUi.launchText(CommandResult(Outcome.UNKNOWN, "")))
    }

    @Test fun unansweredCommandIsUnknownNotFailed() {
        assertEquals(NodeUi.UNKNOWN_RESULT, NodeUi.commandFailure(NodeException(NodeProblem.NO_ANSWER, ""), false))
    }

    @Test fun buttonChoices() {
        assertTrue(NodeUi.showResume("user_paused", true))
        assertTrue(NodeUi.showResume("safety_paused", false))
        assertFalse(NodeUi.showResume("watching", false))
        assertTrue(NodeUi.showTurnOn("disabled"))
        assertTrue(NodeUi.showRepin("certificate_mismatch"))
        assertFalse(NodeUi.showRepin("connected"))
    }

    @Test fun deviceText() {
        assertEquals("None", NodeUi.throttledText("0x0"))
        assertEquals("Yes — check the power supply", NodeUi.throttledText("0x50005"))
        assertEquals("820 MB", NodeUi.mbText(820))
        assertEquals("2.0 GB", NodeUi.mbText(2048))
        assertEquals("2 h 30 min", NodeUi.durationText(9000))
        assertEquals("2 bars · -69 dBm", NodeUi.wifiText(2, -69))
    }

    @Test fun ageLabel() {
        assertEquals("Updated 4 s ago", NodeUi.updatedLabel(4_200))
        assertEquals("Updated just now", NodeUi.updatedLabel(500))
    }

    @Test fun pairingCodeIsCleaned() {
        assertEquals("K7QM29XD", NodeUi.normalizeCode("k7qm-29xd"))
        assertEquals("K7QM29XD", NodeUi.normalizeCode(" K7QM 29XD "))
        assertTrue(NodeUi.codeLooksComplete("K7QM-29XD"))
        assertFalse(NodeUi.codeLooksComplete("K7QM-29"))
    }
}
