package com.designinnsaeit.vhome.watch

import kotlin.math.round

/**
 * Pure state machine: foreground events in, actions out. No I/O, no clock of its own.
 * Every input carries `now` (seconds, any monotonic origin). Port of companion/vhome_companion/watcher.py.
 */
const val CONFIRM_S = 10.0 // launch response AND V/HOME in front within this
const val FAIL_WINDOW_S = 60.0
const val FAIL_LIMIT = 3
const val REDIRECT_WINDOW_S = 120.0
const val REDIRECT_LIMIT = 5
const val DOUBLE_HOME_S = 3.0

private fun log(text: String, level: Level = Level.INFO): Action = Action.Log(text, level)

private class Pending(val token: Int, val sentAt: Double) {
    var ok = false
    var seenAt: Double? = null
}

class Watcher(val vhomeId: String, homeIds: List<String>, val doubleHomeEscape: Boolean = false) {
    val homeIds: List<String> = homeIds.filter { it.isNotBlank() }
    var paused: Boolean = false
    private var lastApp: String? = null
    private var pending: Pending? = null
    private var token = 0
    private val redirects = ArrayDeque<Double>()
    private val failures = ArrayDeque<Double>()
    private val homeTimes = ArrayDeque<Double>()
    private var nRedirects = 0
    private var nOk = 0
    private var nFailed = 0
    private var nEscapes = 0
    private var lastLatencyS: Double? = null
    private var lastFailure: String? = null

    init {
        if (vhomeId.isBlank()) throw ConfigError("V/HOME app id is not set")
        if (this.homeIds.isEmpty()) {
            throw ConfigError(
                "no LG Home app id configured; run `diag --observe 20`, press Home, " +
                    "then `diag --save-home <id>`"
            )
        }
        if (vhomeId in this.homeIds) throw ConfigError("the V/HOME app id must not be one of the LG Home ids")
    }

    // ---- inputs -------------------------------------------------------------------------

    /** New connection: forget the previous foreground so the first event is reconciled. */
    fun onConnected(now: Double): List<Action> {
        val out = mutableListOf<Action>()
        if (pending != null) {
            pending = null
            out += log("connection restarted while a launch was pending; not counted", Level.WARNING)
        }
        lastApp = null
        return out
    }

    fun onForeground(appId: String?, now: Double): List<Action> {
        val out = expire(now).toMutableList()
        val app = appId?.trim() ?: ""
        if (app.isEmpty()) {
            out += log("ignored foreground event without an app id", Level.DEBUG)
            return out
        }
        if (app == lastApp) return out // duplicate notification
        lastApp = app
        out += log("foreground: $app")
        val p = pending
        if (p != null && app == vhomeId) {
            p.seenAt = now
            out += maybeConfirm()
        }
        if (app in homeIds) out += onHome(now)
        return out
    }

    fun onLaunchResult(token: Int, ok: Boolean, now: Double, error: String = ""): List<Action> {
        val out = expire(now)
        val p = pending
        if (p == null || p.token != token) return out + log("late launch result ignored", Level.DEBUG)
        if (!ok) return out + fail(now, "launch rejected: ${error.ifEmpty { "unknown error" }}")
        p.ok = true
        return out + maybeConfirm()
    }

    fun onTick(now: Double): List<Action> = expire(now)

    /** TV power is active: failures while it was booting must not count towards the breaker. */
    fun onPowerActive(now: Double): List<Action> {
        failures.clear()
        return listOf(log("TV power active: failure window cleared", Level.DEBUG))
    }

    fun nextDeadline(): Double? = pending?.let { it.sentAt + CONFIRM_S }

    fun pause(reason: String = "paused"): List<Action> {
        paused = true
        return listOf(log("paused: $reason", Level.WARNING))
    }

    fun resume(): List<Action> {
        paused = false
        pending = null // lastApp kept: resume acts on the next real Home transition, not the screen already showing
        redirects.clear()
        failures.clear()
        homeTimes.clear()
        return listOf(log("resumed"))
    }

    fun snapshot(): Snapshot = Snapshot(
        paused, lastApp, pending != null, nRedirects, nOk, nFailed, nEscapes, lastLatencyS, lastFailure,
    )

    // ---- internals ----------------------------------------------------------------------

    private fun onHome(now: Double): List<Action> {
        while (homeTimes.isNotEmpty() && now - homeTimes.first() > DOUBLE_HOME_S) homeTimes.removeFirst()
        val recentHome = homeTimes.isNotEmpty()
        homeTimes.addLast(now)
        if (paused) return listOf(log("LG Home seen while paused: observing only"))
        if (doubleHomeEscape && recentHome) {
            homeTimes.clear()
            nEscapes++
            return listOf(log("Home pressed twice: staying on LG Home"))
        }
        if (pending != null) return listOf(log("LG Home seen while a launch is in flight: not launching again"))
        while (redirects.isNotEmpty() && now - redirects.first() > REDIRECT_WINDOW_S) redirects.removeFirst()
        if (redirects.size >= REDIRECT_LIMIT) {
            paused = true
            return listOf(
                log(
                    "more than $REDIRECT_LIMIT redirects in ${REDIRECT_WINDOW_S.toInt()} s; " +
                        "pausing (is V/HOME crashing?)",
                    Level.ERROR,
                ),
                Action.Pause("redirect loop breaker"),
            )
        }
        token++
        redirects.addLast(now)
        nRedirects++
        pending = Pending(token, now)
        return listOf(log("LG Home -> V/HOME"), Action.Launch(token, vhomeId))
    }

    private fun maybeConfirm(): List<Action> {
        val p = pending
        val seen = p?.seenAt
        if (p == null || !p.ok || seen == null) return emptyList()
        pending = null
        nOk++
        val latency = round((seen - p.sentAt) * 1000) / 1000
        lastLatencyS = latency
        return listOf(log("redirect ok in $latency s"))
    }

    private fun expire(now: Double): List<Action> {
        val p = pending
        if (p != null && now - p.sentAt > CONFIRM_S) {
            val why = if (!p.ok) "no launch response from the TV" else "V/HOME did not come to the front"
            return fail(now, "$why within ${CONFIRM_S.toInt()} s")
        }
        return emptyList()
    }

    private fun fail(now: Double, reason: String): List<Action> {
        pending = null
        // lastApp stays: repeated notifications of the same Home are not a new transition (brief: do not loop)
        nFailed++
        lastFailure = reason
        failures.addLast(now)
        while (failures.isNotEmpty() && now - failures.first() > FAIL_WINDOW_S) failures.removeFirst()
        val out = mutableListOf<Action>(log("redirect failed: $reason", Level.WARNING))
        if (failures.size >= FAIL_LIMIT) {
            paused = true
            out += log("$FAIL_LIMIT failed redirects in ${FAIL_WINDOW_S.toInt()} s; pausing", Level.ERROR)
            out += Action.Pause("failed redirect breaker")
        }
        return out
    }
}
