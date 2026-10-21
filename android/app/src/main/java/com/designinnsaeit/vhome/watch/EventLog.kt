package com.designinnsaeit.vhome.watch

import android.content.Context
import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Last 80 watcher events, kept in private prefs so the settings screen can show and copy them. */
object EventLog {
    private const val PREFS = "vhome_watch_log"
    private const val MAX = 80
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.US)

    @Synchronized
    fun add(ctx: Context, text: String) {
        val line = "${fmt.format(Date())} ${redact(text)}"
        Log.i("VHome", line)
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val lines = (p.getString("lines", "")!!.lines().filter { it.isNotEmpty() } + line).takeLast(MAX)
        p.edit().putString("lines", lines.joinToString("\n")).apply()
    }

    fun read(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("lines", "")!!
}
