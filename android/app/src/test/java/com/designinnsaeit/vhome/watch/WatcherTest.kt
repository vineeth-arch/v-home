package com.designinnsaeit.vhome.watch

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

private const val VH = "com.designinnsaeit.vhome"
private const val HOME = "com.webos.app.home"

private fun launches(a: List<Action>) = a.filterIsInstance<Action.Launch>()
private fun pauses(a: List<Action>) = a.filterIsInstance<Action.Pause>()
private fun make(escape: Boolean = false) = Watcher(VH, listOf(HOME), escape)

/** Home at t, launch accepted, V/HOME in front at t+1. Returns the launch action. */
private fun redirectOk(w: Watcher, t: Double): Action.Launch {
    val a = launches(w.onForeground(HOME, t)).single()
    w.onLaunchResult(a.token, true, t + 0.5)
    w.onForeground(VH, t + 1)
    return a
}

class WatcherTest {
    private fun assertConfigError(block: () -> Unit) {
        try {
            block()
            fail("expected ConfigError")
        } catch (e: ConfigError) {
        }
    }

    @Test fun configErrors() {
        assertConfigError { Watcher(VH, emptyList()) }
        assertConfigError { Watcher(VH, listOf("", "  ")) }
        assertConfigError { Watcher("", listOf(HOME)) }
        assertConfigError { Watcher(VH, listOf(VH)) }
    }

    @Test fun homeLaunchesOnceAndConfirms() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        assertEquals(VH, a.appId)
        w.onLaunchResult(a.token, true, 0.4)
        assertTrue(w.snapshot().pending) // still waiting for V/HOME to be in front
        val out = w.onForeground(VH, 1.0)
        assertFalse(w.snapshot().pending)
        assertEquals(1, w.snapshot().ok)
        assertEquals(1.0, w.snapshot().lastLatencyS!!, 0.0)
        assertTrue(launches(out).isEmpty())
    }

    @Test fun duplicateEventsDoNotRelaunch() {
        val w = make()
        val total = launches(w.onForeground(HOME, 0.0)) + launches(w.onForeground(HOME, 0.1)) +
            launches(w.onForeground(HOME, 0.2))
        assertEquals(1, total.size)
    }

    @Test fun vhomeInFrontBeforeResponse() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        w.onForeground(VH, 0.5)
        assertTrue(w.snapshot().pending) // still needs the launch response
        w.onLaunchResult(a.token, true, 0.8)
        assertFalse(w.snapshot().pending)
        assertEquals(1, w.snapshot().ok)
    }

    @Test fun unknownForegroundIsNeverHome() {
        val w = make()
        for (app in listOf("", null, "   ", "some.other.app")) {
            assertTrue(launches(w.onForeground(app, 0.0)).isEmpty())
        }
        assertEquals(0, w.snapshot().redirects)
    }

    @Test fun emptyEventDoesNotMakeANewTransition() {
        val w = make()
        var n = launches(w.onForeground(HOME, 0.0)).size
        n += launches(w.onForeground("", 0.1)).size
        n += launches(w.onForeground(HOME, 0.2)).size
        assertEquals(1, n)
    }

    @Test fun launchDeniedIsAFailureWithoutRetry() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        val out = w.onLaunchResult(a.token, false, 0.3, "insufficient permissions")
        assertFalse(w.snapshot().pending)
        assertEquals(1, w.snapshot().failed)
        assertTrue(w.snapshot().lastFailure!!.contains("insufficient permissions"))
        assertTrue(launches(out).isEmpty())
        assertTrue(launches(w.onTick(30.0)).isEmpty())
        assertTrue(launches(w.onForeground(HOME, 40.0)).isEmpty()) // same Home still showing: dedupe
    }

    @Test fun launchTimeoutNoResponse() {
        val w = make()
        w.onForeground(HOME, 0.0)
        assertEquals(10.0, w.nextDeadline()!!, 0.0)
        assertTrue(w.onTick(10.0).isEmpty()) // exactly at the limit is still fine
        val out = w.onTick(10.1)
        assertFalse(w.snapshot().pending)
        assertTrue(w.snapshot().lastFailure!!.contains("no launch response"))
        assertTrue(out.isNotEmpty())
    }

    @Test fun responseOkButVhomeNeverAppears() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        w.onLaunchResult(a.token, true, 0.5)
        w.onTick(10.5)
        assertTrue(w.snapshot().lastFailure!!.contains("did not come to the front"))
    }

    @Test fun vhomeLateAfterDeadlineIsFailure() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        w.onLaunchResult(a.token, true, 0.5)
        w.onForeground(VH, 11.0)
        assertEquals(1, w.snapshot().failed)
        assertEquals(0, w.snapshot().ok)
    }

    @Test fun missingVhomeApp() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        w.onLaunchResult(a.token, false, 0.2, "Application not found")
        assertEquals(1, w.snapshot().failed)
    }

    @Test fun lateResultIgnored() {
        val w = make()
        val a = launches(w.onForeground(HOME, 0.0)).single()
        w.onTick(11.0)
        w.onLaunchResult(a.token, true, 12.0)
        assertEquals(0, w.snapshot().ok)
    }

    @Test fun breakerThreeFailuresIn60s() {
        val w = make()
        val ps = mutableListOf<Action.Pause>()
        for (t in listOf(0.0, 10.0, 20.0)) {
            val a = launches(w.onForeground(HOME, t)).single()
            ps += pauses(w.onLaunchResult(a.token, false, t + 1, "nope"))
            w.onForeground("x.other", t + 2)
        }
        assertEquals(1, ps.size)
        assertTrue(w.paused)
        assertTrue(launches(w.onForeground(HOME, 30.0)).isEmpty())
    }

    @Test fun failuresSpreadOutDoNotTrip() {
        val w = make()
        for (t in listOf(0.0, 40.0, 80.0, 120.0)) {
            val a = launches(w.onForeground(HOME, t)).single()
            w.onLaunchResult(a.token, false, t + 1, "nope")
            w.onForeground("x.other", t + 2)
        }
        assertFalse(w.paused)
    }

    @Test fun breakerMoreThanFiveRedirectsIn120s() {
        val w = make()
        for (i in 0 until 5) redirectOk(w, i * 10.0)
        val out = w.onForeground(HOME, 55.0)
        assertEquals(0, launches(out).size)
        assertEquals(1, pauses(out).size)
        assertTrue(w.paused)
    }

    @Test fun redirectBreakerPauses() {
        val w = make()
        for (i in 0 until 5) redirectOk(w, i * 10.0)
        // 6th Home transition, still within 120 s of the first
        val out = w.onForeground("x.other", 51.0) + w.onForeground(HOME, 52.0)
        assertEquals(1, pauses(out).size)
        assertTrue(w.paused)
    }

    @Test fun redirectsSpreadBeyondWindowDoNotTrip() {
        val w = make()
        for (i in 0 until 8) redirectOk(w, i * 30.0)
        assertFalse(w.paused)
        assertEquals(8, w.snapshot().redirects)
    }

    @Test fun resumeClearsBreakerAndNeedsANewTransition() {
        val w = make()
        for (i in 0 until 5) redirectOk(w, i * 10.0)
        w.onForeground(HOME, 55.0) // trips
        w.resume()
        assertTrue(launches(w.onForeground(HOME, 60.0)).isEmpty()) // Home never left: no new transition
        w.onForeground("x.other", 61.0)
        assertEquals(1, launches(w.onForeground(HOME, 62.0)).size)
    }

    @Test fun pausedObservesOnly() {
        val w = make()
        w.pause("test")
        assertTrue(launches(w.onForeground(HOME, 0.0)).isEmpty())
        w.onForeground("x.other", 1.0)
        assertTrue(launches(w.onForeground(HOME, 2.0)).isEmpty())
        assertEquals(0, w.snapshot().redirects)
        w.resume()
        w.onForeground("x.other", 3.0)
        assertEquals(1, launches(w.onForeground(HOME, 4.0)).size)
    }

    @Test fun reconnectReconcilesCurrentForeground() {
        val w = make()
        w.onForeground("netflix", 0.0)
        w.onConnected(5.0)
        assertTrue(launches(w.onForeground("netflix", 5.0)).isEmpty()) // other app: never interrupted
        w.onConnected(6.0)
        assertTrue(launches(w.onForeground(VH, 6.0)).isEmpty())
        w.onConnected(7.0)
        assertEquals(1, launches(w.onForeground(HOME, 7.0)).size) // TV is on Home: act
    }

    @Test fun reconnectDropsPendingLaunchWithoutCounting() {
        val w = make()
        w.onForeground(HOME, 0.0)
        w.onConnected(1.0)
        assertFalse(w.snapshot().pending)
        assertEquals(0, w.snapshot().failed)
    }

    @Test fun hdmiInputIsNeverInterrupted() {
        val w = make()
        assertTrue(launches(w.onForeground("com.webos.app.hdmi1", 0.0)).isEmpty())
    }

    private fun doublePress(w: Watcher): List<Action.Launch> {
        redirectOk(w, 0.0)
        w.onForeground("netflix", 1.0)
        return launches(w.onForeground(HOME, 2.0))
    }

    @Test fun doubleHomeOffRedirectsTwice() {
        assertEquals(1, doublePress(make()).size)
    }

    @Test fun doubleHomeOnSkipsSecond() {
        val w = make(escape = true)
        assertTrue(doublePress(w).isEmpty())
        assertEquals(1, w.snapshot().escapes)
    }

    @Test fun doubleHomeOnSlowSecondPressRedirects() {
        val w = make(escape = true)
        redirectOk(w, 0.0)
        w.onForeground("netflix", 1.0)
        assertEquals(1, launches(w.onForeground(HOME, 3.5)).size)
    }

    @Test fun doubleHomeOnDuplicateNotificationIsNotASecondPress() {
        val w = make(escape = true)
        val out = w.onForeground(HOME, 0.0) + w.onForeground(HOME, 0.5)
        assertEquals(1, launches(out).size)
        assertEquals(0, w.snapshot().escapes)
    }

    @Test fun homeDuringInflightLaunchDoesNotDoubleLaunch() {
        val w = make()
        w.onForeground(HOME, 0.0)
        w.onForeground("x.other", 1.0)
        assertTrue(launches(w.onForeground(HOME, 2.0)).isEmpty())
    }

    @Test fun powerActiveClearsFailures() {
        val w = make()
        val out = mutableListOf<Action>()
        for (t in listOf(0.0, 10.0)) {
            val a = launches(w.onForeground(HOME, t)).single()
            out += w.onLaunchResult(a.token, false, t + 1, "tv booting")
            w.onForeground("x.other", t + 2)
        }
        out += w.onPowerActive(21.0)
        val a = launches(w.onForeground(HOME, 22.0)).single()
        out += w.onLaunchResult(a.token, false, 23.0, "tv booting")
        assertTrue(pauses(out).isEmpty())
        assertFalse(w.paused)
        assertNotNull(w.snapshot().lastFailure)
    }
}
