package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceTimeBy
import kotlinx.coroutines.test.currentTime
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private class RedirectFake : TvSession {
    val fg = MutableSharedFlow<JSONObject>(extraBufferCapacity = 64)
    override val certSha256: String? = null
    override suspend fun open(onPrompt: () -> Unit) = "key"
    override suspend fun request(uri: String, payload: JSONObject, timeoutMs: Long): JSONObject = JSONObject()
    override fun subscribe(uri: String, payload: JSONObject): Flow<JSONObject> =
        if (uri == FG_URI) fg else MutableSharedFlow(extraBufferCapacity = 1)
    override fun close() {}
}

@OptIn(ExperimentalCoroutinesApi::class)
class WatchStateTest {
    @Test fun notificationTextCoversAllStates() {
        for (s in WatchState.values()) assertTrue(s.name, notificationText(s).isNotBlank())
        assertEquals("Paused", notificationText(WatchState.PAUSED))
        assertTrue(notificationText(WatchState.PAUSED, 1_000_000L).startsWith("Paused until "))
    }

    @Test fun timedPauseResumesWhenDue() {
        assertFalse(shouldResume(null, 10L))
        assertFalse(shouldResume(100L, 99L))
        assertTrue(shouldResume(100L, 100L))
        assertTrue(shouldResume(100L, 101L))
    }

    @Test fun runnerReportsRedirect() = runTest {
        val s = RedirectFake()
        val seen = mutableListOf<Double>()
        val runner = Runner(Watcher("vh", listOf("home")), s, {}, { currentTime / 1000.0 }, onRedirect = { seen += it })
        backgroundScope.launch { runner.session() }
        runCurrent()
        s.fg.tryEmit(JSONObject().put("appId", "home")); runCurrent()
        s.fg.tryEmit(JSONObject().put("appId", "vh")); runCurrent()
        advanceTimeBy(5_000)
        assertEquals(1, seen.size)
    }
}
