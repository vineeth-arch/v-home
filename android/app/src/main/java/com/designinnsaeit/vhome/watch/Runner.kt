package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Locale

private val POWER_OFF = setOf("Active Standby", "Suspend", "Power Off")
private val WAKE_CHECK_GAPS_MS = listOf(0L, 3_000L, 7_000L) // checks at 0 s, 3 s, 10 s after wake

class WakeCheckFailed(msg: String) : Exception(msg)

/** Glue between the TV session and the pure Watcher. All decisions live in the Watcher. */
class Runner(
    private val watcher: Watcher, private val session: TvSession,
    private val persistPaused: (Boolean) -> Unit, private val clock: () -> Double,
    private val status: (String) -> Unit = {},
    private val log: (String) -> Unit = {},
    private val retryDelayMs: Long = 2_000, private val retryWindowMs: Long = 8_000,
) {
    private val lock = Any() // watcher is single-threaded; nothing suspends while it is held
    @Volatile private var power: String? = null
    @Volatile private var scope: CoroutineScope? = null
    private var okSeen = 0

    /** Runs until the foreground flow ends. Rethrows NotPaired / PinMismatch. */
    suspend fun session() = coroutineScope {
        scope = this
        try {
            apply(locked { watcher.onConnected(clock()) })
            status(if (watcher.paused) "Paused" else "Watching")
            val kids = listOf(launch { watchPower() }, launch { tick() })
            try {
                session.subscribe(FG_URI).collect { p ->
                    val app = extractAppId(p)
                    if (app in watcher.homeIds && power in POWER_OFF) {
                        status("Home ignored while TV power is $power")
                    } else {
                        apply(locked { watcher.onForeground(app, clock()) })
                    }
                }
            } finally {
                kids.forEach { it.cancel() }
            }
        } finally {
            scope = null
        }
    }

    fun pause() {
        apply(locked { watcher.pause("paused by user") })
        persistPaused(true)
        status("Paused")
    }

    fun resume() {
        apply(locked { watcher.resume() })
        persistPaused(false)
        status("Watching")
    }

    fun extractAppId(payload: JSONObject): String {
        (payload.opt("appId") as? String)?.let { return it }
        val info = payload.optJSONArray("foregroundAppInfo") ?: return ""
        for (i in 0 until info.length()) {
            (info.optJSONObject(i)?.opt("appId") as? String)?.let { return it }
        }
        return ""
    }

    private fun <T> locked(block: () -> T): T = synchronized(lock, block)

    private suspend fun watchPower() {
        try {
            session.subscribe(POWER_URI).collect { p ->
                val s = p.optString("state").ifEmpty { null } ?: return@collect
                val was = power
                power = s
                if (s != was) log("TV power: $s")
                if (s == "Active" && was != "Active") {
                    apply(locked { watcher.onPowerActive(clock()) })
                    scope?.launch { wakeCheck() }
                }
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            power = null
            status("TV power state unavailable; watching anyway")
        }
    }

    /**
     * After the TV wakes: check the link still answers (else end the session so the service reconnects),
     * then redirect if webOS booted into LG Home — that event may have arrived while power still read standby.
     * Re-checks cover a slow boot where the foreground app isn't known yet.
     */
    private suspend fun wakeCheck() {
        for (waitMs in WAKE_CHECK_GAPS_MS) {
            delay(waitMs)
            val app = try {
                extractAppId(session.request(FG_URI, JSONObject(), 5_000))
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                throw WakeCheckFailed("TV did not answer after waking: ${e.message ?: e.javaClass.simpleName}")
            }
            if (app == watcher.vhomeId) return
            if (app in watcher.homeIds) {
                // One locked step, so a live Home event can't launch in between. onConnected forgets the
                // last app, so the Home already on screen counts as a fresh transition.
                apply(locked {
                    if (watcher.snapshot().pending) emptyList()
                    else watcher.onConnected(clock()) + watcher.onForeground(app, clock())
                })
                return
            }
            if (app.isNotEmpty()) return // some other app is up: nothing to fix
        }
    }

    private suspend fun tick() {
        while (true) {
            delay(1_000)
            val due = locked { watcher.nextDeadline() }
            if (due != null && clock() >= due) apply(locked { watcher.onTick(clock()) })
        }
    }

    private fun apply(actions: List<Action>) {
        for (a in actions) when (a) {
            is Action.Log -> if (a.level == Level.WARNING || a.level == Level.ERROR) status(a.text) else log(a.text)
            is Action.Pause -> { persistPaused(true); status("Paused") }
            is Action.Launch -> scope?.launch { launchWithRetry(a) }
        }
        val s = locked { watcher.snapshot() }
        if (s.ok > okSeen) {
            okSeen = s.ok
            s.lastLatencyS?.let { status(String.format(Locale.US, "Watching · last redirect %.2f s", it)) }
        }
    }

    /** The TV may still be booting: retry, but report before the watcher's own 10 s window runs out. */
    private suspend fun launchWithRetry(a: Action.Launch) {
        val start = clock()
        var err: String
        while (true) {
            try {
                session.request(LAUNCH_URI, JSONObject().put("id", a.appId), 10_000)
                apply(locked { watcher.onLaunchResult(a.token, true, clock()) })
                return
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                err = e.message ?: e.javaClass.simpleName
            }
            if ((clock() - start) * 1000 + retryDelayMs >= retryWindowMs) break
            delay(retryDelayMs)
        }
        apply(locked { watcher.onLaunchResult(a.token, false, clock(), err) })
    }
}

/** Reconnect delay in seconds: 5 * 2^attempt, capped at 300, +-20% jitter, never above the cap. */
fun backoff(attempt: Int, rand: () -> Double = Math::random): Double {
    val base = minOf(300.0, 5.0 * (1L shl attempt.coerceIn(0, 10)))
    return minOf(300.0, base * (1 + (rand() * 2 - 1) * 0.2))
}
