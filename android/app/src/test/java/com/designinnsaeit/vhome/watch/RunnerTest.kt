package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private const val VH = "com.designinnsaeit.vhome"
private const val HOME = "com.webos.app.home"

@OptIn(ExperimentalCoroutinesApi::class)
private class FakeSession(val scope: TestScope) : TvSession {
    val fg = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)
    val power = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)
    var powerFails = false
    val launchTimes = mutableListOf<Long>()
    val closeTimes = mutableListOf<Long>()
    val launchScript = ArrayDeque<Boolean>() // true = ok, false = throw; empty = ok
    var alwaysFail = false

    override val certSha256: String? = null
    override suspend fun open(onPrompt: () -> Unit) = "key"
    val fgAnswers = ArrayDeque<String>() // scripted answers to the wake check's foreground query
    var fgQueryFails = false
    var fgQueries = 0

    override suspend fun request(uri: String, payload: JSONObject, timeoutMs: Long): JSONObject {
        if (uri == FG_URI) {
            fgQueries++
            if (fgQueryFails) throw RuntimeException("no answer")
            return fgOf(fgAnswers.removeFirstOrNull() ?: VH)
        }
        if (uri == "ssap://system.launcher/close") {
            closeTimes += scope.currentTime
            return JSONObject()
        }
        check(uri == LAUNCH_URI)
        launchTimes += scope.currentTime
        val ok = !alwaysFail && (launchScript.removeFirstOrNull() ?: true)
        if (!ok) throw RuntimeException("booting")
        return JSONObject()
    }
    override fun subscribe(uri: String, payload: JSONObject): Flow<JSONObject> = when (uri) {
        FG_URI -> fg
        POWER_URI -> if (powerFails) flow { throw RuntimeException("denied") } else power
        else -> error(uri)
    }
    override fun close() {}
}

private fun fgOf(app: String) = JSONObject().put("appId", app)
private fun powerOf(state: String) = JSONObject().put("state", state)

@OptIn(ExperimentalCoroutinesApi::class)
private class Rig(val t: TestScope) {
    val session = FakeSession(t)
    val watcher = Watcher(VH, listOf(HOME))
    val persisted = mutableListOf<Boolean>()
    val runner = Runner(watcher, session, { persisted += it }, { t.currentTime / 1000.0 })

    fun start() {
        t.backgroundScope.launch { runner.session() }
        t.runCurrent()
    }
    fun fg(app: String) { session.fg.tryEmit(fgOf(app)); t.runCurrent() }
    fun power(s: String) { session.power.tryEmit(powerOf(s)); t.runCurrent() }
}

@OptIn(ExperimentalCoroutinesApi::class)
class RunnerTest {
    @Test fun homeIgnoredUnlessActive() = runTest {
        val r = Rig(this); r.start()
        r.power("Active Standby")
        r.fg(HOME)
        advanceTimeBy(1_000)
        assertTrue(r.session.launchTimes.isEmpty())
    }

    @Test fun homeAllowedWhenPowerUnknown() = runTest {
        val r = Rig(this); r.start()
        r.fg(HOME)
        assertEquals(1, r.session.launchTimes.size)
    }

    @Test fun powerSubscriptionFailureKeepsWatching() = runTest {
        val r = Rig(this); r.session.powerFails = true; r.start()
        r.fg(HOME)
        assertEquals(1, r.session.launchTimes.size)
    }

    @Test fun launchRetriedWhileBooting() = runTest {
        val r = Rig(this); r.start()
        r.session.launchScript.addAll(listOf(false, false, true))
        r.fg(HOME)
        advanceTimeBy(4_500)
        assertEquals(listOf(0L, 2_000L, 4_000L), r.session.launchTimes)
        r.fg(VH)
        assertEquals(1, r.watcher.snapshot().ok)
    }

    @Test fun launchGivesUpWithinConfirmWindow() = runTest {
        val r = Rig(this); r.session.alwaysFail = true; r.start()
        r.fg(HOME)
        advanceTimeBy(9_000)
        assertEquals(1, r.watcher.snapshot().failed)
        assertTrue(currentTime < 10_000)
    }

    @Test fun pausePersists() = runTest {
        val r = Rig(this); r.session.alwaysFail = true; r.start()
        repeat(3) {
            r.fg(HOME)
            advanceTimeBy(9_000)
            r.fg("other.app")
        }
        assertTrue(r.watcher.paused)
        assertEquals(listOf(true), r.persisted)
    }

    @Test fun powerActiveCallsWatcher() = runTest {
        val r = Rig(this); r.session.alwaysFail = true; r.start()
        repeat(2) {
            r.fg(HOME)
            advanceTimeBy(9_000)
            r.fg("other.app")
        }
        r.power("Active")
        r.fg(HOME)
        advanceTimeBy(9_000)
        assertEquals(3, r.watcher.snapshot().failed)
        assertFalse(r.watcher.paused)
        assertTrue(r.persisted.isEmpty())
    }

    @Test fun extractAppIdArrayForm() {
        val idle = object : TvSession {
            override val certSha256: String? = null
            override suspend fun open(onPrompt: () -> Unit) = ""
            override suspend fun request(uri: String, payload: JSONObject, timeoutMs: Long) = JSONObject()
            override fun subscribe(uri: String, payload: JSONObject): Flow<JSONObject> = flow {}
            override fun close() {}
        }
        val r = Runner(Watcher(VH, listOf(HOME)), idle, {}, { 0.0 })
        val arr = JSONObject().put("foregroundAppInfo", JSONArray().put(JSONObject().put("appId", "x.y")))
        assertEquals("x.y", r.extractAppId(arr))
        assertEquals("a.b", r.extractAppId(fgOf("a.b")))
        assertEquals("", r.extractAppId(JSONObject()))
    }

    @Test fun backoffCapsAt300() {
        assertTrue(backoff(30) { 1.0 } <= 300.0)
        assertTrue(backoff(30) { 0.0 } <= 300.0)
    }

    @Test fun wakeRedirectsWhenBootedIntoHome() = runTest {
        val r = Rig(this); r.start()
        r.power("Active Standby")
        r.fg(HOME) // arrives while still reading standby: ignored
        assertTrue(r.session.launchTimes.isEmpty())
        r.session.fgAnswers += HOME
        r.power("Active")
        assertEquals(1, r.session.launchTimes.size)
    }

    @Test fun wakeRechecksWhileBooting() = runTest {
        val r = Rig(this); r.start()
        r.power("Suspend")
        r.session.fgAnswers += listOf("", "", HOME) // foreground unknown until the third check
        r.power("Active")
        assertTrue(r.session.launchTimes.isEmpty())
        advanceTimeBy(10_001)
        assertEquals(3, r.session.fgQueries)
        assertEquals(1, r.session.launchTimes.size)
    }

    @Test fun wakeNoRedirectWhenVhomeAlreadyUp() = runTest {
        val r = Rig(this); r.start()
        r.power("Active Standby")
        r.session.fgAnswers += VH
        r.power("Active")
        advanceTimeBy(11_000)
        assertEquals(1, r.session.fgQueries)
        assertTrue(r.session.launchTimes.isEmpty())
    }

    @Test fun wakeCheckFailureEndsSession() = runTest {
        val s = FakeSession(this).apply { fgQueryFails = true }
        val runner = Runner(Watcher(VH, listOf(HOME)), s, {}, { currentTime / 1000.0 })
        var failure: Throwable? = null
        backgroundScope.launch { failure = runCatching { runner.session() }.exceptionOrNull() }
        runCurrent()
        s.power.tryEmit(powerOf("Active")); runCurrent()
        assertTrue(failure is WakeCheckFailed)
    }

    @Test fun stuckVhomeIsRestarted() = runTest {
        val r = Rig(this); r.start()
        r.fg(HOME) // launch "succeeds" but V/HOME never shows
        assertEquals(1, r.session.launchTimes.size)
        advanceTimeBy(3_001); runCurrent()
        assertEquals(1, r.session.closeTimes.size)
        advanceTimeBy(1_001); runCurrent()
        assertEquals(2, r.session.launchTimes.size)
        r.fg(VH) // the fresh instance comes to the front
        assertEquals(1, r.watcher.snapshot().ok)
        assertEquals(0, r.watcher.snapshot().failed)
    }

    @Test fun noRestartWhenVhomeAppears() = runTest {
        val r = Rig(this); r.start()
        r.fg(HOME)
        r.fg(VH)
        advanceTimeBy(5_000)
        assertTrue(r.session.closeTimes.isEmpty())
        assertEquals(1, r.session.launchTimes.size)
    }

    @Test fun backoffStartsAt5() {
        assertEquals(5.0, backoff(0) { 0.5 }, 1e-9)
        assertEquals(10.0, backoff(1) { 0.5 }, 1e-9)
    }
}
