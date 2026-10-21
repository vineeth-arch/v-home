package com.designinnsaeit.vhome.watch

import android.content.Context
import android.content.SharedPreferences
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

// Shared contract between WatcherService (writes) and MainActivity (reads, live via a prefs listener).
// Owned by Wave 0; parallel tasks consume it and must not edit this file.

enum class WatchState { NOT_PAIRED, WAITING_WIFI, AWAY, LOOKING, TV_OFF, CONNECTING, WATCHING, PAUSED, PROBLEM }

data class Status(val state: WatchState, val line: String, val since: Long, val lastRedirectS: Double?, val lastRedirectAt: Long?)

/** One plain sentence: what the state means and what happens next. Used by the app and the notification. */
fun explain(s: WatchState): String = when (s) {
    WatchState.NOT_PAIRED -> "Pair once with your TV and the watcher runs by itself."
    WatchState.WAITING_WIFI -> "Not on Wi-Fi. Watching starts when you're home."
    WatchState.AWAY -> "This Wi-Fi isn't home. Watching starts when you're back."
    WatchState.LOOKING -> "Finding your TV on this Wi-Fi."
    WatchState.TV_OFF -> "TV is off. Watching resumes on its own when you switch it on."
    WatchState.CONNECTING -> "Connecting to your TV."
    WatchState.WATCHING -> "Home on the TV opens V/HOME."
    WatchState.PAUSED -> "The Home button goes to LG Home until you resume."
    WatchState.PROBLEM -> "Something needs fixing. Open the app."
}

object WatchStatus {
    const val PREFS = Notify.STATUS_PREFS
    const val ACTION_RESTART = "com.designinnsaeit.vhome.watch.RESTART"
    const val EXTRA_MINUTES = "minutes"

    private val day = SimpleDateFormat("yyyy-MM-dd", Locale.US)
    private fun p(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
    private fun today() = day.format(Date())

    /** `since` moves only when the state changes; the legacy "line" key keeps older readers working. */
    fun write(ctx: Context, state: WatchState, line: String) {
        val p = p(ctx)
        val e = p.edit().putString("state", state.name).putString("line", line)
        if (p.getString("state", null) != state.name) e.putLong("since", System.currentTimeMillis())
        e.apply()
    }

    fun redirected(ctx: Context, seconds: Double) {
        val p = p(ctx)
        val count = redirectsToday(p, today()) + 1
        p.edit().putFloat("last_redirect_s", seconds.toFloat()).putLong("last_redirect_at", System.currentTimeMillis())
            .putString("count_day", today()).putInt("count", count).apply()
    }

    fun read(ctx: Context): Status {
        val p = p(ctx)
        val fallback = if (Prefs.load(ctx).pin == null) WatchState.NOT_PAIRED else WatchState.WAITING_WIFI
        val state = p.getString("state", null)?.let { n -> WatchState.values().firstOrNull { it.name == n } } ?: fallback
        return Status(
            state, p.getString("line", "") ?: "", p.getLong("since", 0L),
            if (p.contains("last_redirect_s")) p.getFloat("last_redirect_s", 0f).toDouble() else null,
            if (p.contains("last_redirect_at")) p.getLong("last_redirect_at", 0L) else null,
        )
    }

    fun pausedUntil(ctx: Context): Long? = p(ctx).getLong("paused_until", 0L).takeIf { it > 0 }

    fun setPausedUntil(ctx: Context, at: Long?) {
        p(ctx).edit().apply { if (at == null) remove("paused_until") else putLong("paused_until", at) }.apply()
    }

    fun redirectsToday(ctx: Context): Int = redirectsToday(p(ctx), today())

    /** Count stored for [today], or 0 once the local date has moved on. */
    fun redirectsToday(p: SharedPreferences, today: String): Int =
        if (p.getString("count_day", null) == today) p.getInt("count", 0) else 0
}
