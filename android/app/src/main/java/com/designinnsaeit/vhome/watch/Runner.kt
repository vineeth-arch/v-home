package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import org.json.JSONObject
import java.util.Locale

private val POWER_OFF = setOf("Active Standby", "Suspend", "Power Off")

/** Glue between the TV session and the pure Watcher. All decisions live in the Watcher. */
class Runner(
    private val watcher: Watcher, private val session: TvSession,
    private val persistPaused: (Boolean) -> Unit, private val clock: () -> Double,
    private val status: (String) -> Unit = {},
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
                if (s == "Active" && was != "Active") apply(locked { watcher.onPowerActive(clock()) })
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            power = null
            status("TV power state unavailable; watching anyway")
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
            is Action.Log -> if (a.level == Level.WARNING || a.level == Level.ERROR) status(a.text)
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
