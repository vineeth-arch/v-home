package com.designinnsaeit.vhome.watch

import android.content.Context
import android.os.Build
import android.os.Process
import android.util.Log
import java.io.PrintWriter
import java.io.StringWriter
import java.net.InetSocketAddress
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import javax.net.SocketFactory

/**
 * Last 80 watcher events, kept in private prefs so the settings screen can show and copy them,
 * and pushed live to a log receiver on the owner's Mac (android/tools/logsink.py) when one is set.
 */
object EventLog {
    private const val PREFS = "vhome_watch_log"
    private const val MAX = 80
    private val fmt = SimpleDateFormat("HH:mm:ss", Locale.US)
    private val sender = Executors.newSingleThreadExecutor() // keeps lines in order, never blocks callers

    @Synchronized
    fun add(ctx: Context, text: String) {
        val line = "${fmt.format(Date())} ${redact(text)}"
        Log.i("VHome", line)
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val lines = (p.getString("lines", "")!!.lines().filter { it.isNotEmpty() } + line).takeLast(MAX)
        p.edit().putString("lines", lines.joinToString("\n")).apply()
        val app = ctx.applicationContext
        sender.execute { push(app, line + "\n") }
    }

    fun read(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("lines", "")!!

    /** "host:port" of the Mac log receiver; empty = off. Defaults to the build machine's (local.properties). */
    fun sink(ctx: Context): String =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString("sink", null) ?: BuildConfig.LOG_SINK

    fun setSink(ctx: Context, value: String) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("sink", value.trim()).apply()
    }

    fun header(ctx: Context): String {
        val c = Prefs.load(ctx)
        val v = ctx.packageManager.getPackageInfo(ctx.packageName, 0).versionName
        return "V/HOME Watcher $v · Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT}, " +
            "${Build.MANUFACTURER} ${Build.MODEL}) · host ${c.host} · paired ${c.pin != null} · " +
            "paused ${c.paused} · home ids ${c.homeIds} · vhome ${c.vhomeId}"
    }

    /** Everything useful in one go: header, event history, and this app's own logcat (no permission needed). */
    fun fullDump(ctx: Context): String = buildString {
        appendLine("===== FULL DUMP ${fmt.format(Date())} =====")
        appendLine(redact(header(ctx)))
        appendLine("--- events ---")
        appendLine(read(ctx))
        appendLine("--- logcat (this app) ---")
        appendLine(redact(ownLogcat()))
        appendLine("===== END DUMP =====")
    }

    fun sendFullDump(ctx: Context, done: (Boolean) -> Unit) {
        val app = ctx.applicationContext
        sender.execute { done(push(app, fullDump(app))) }
    }

    /** Record any uncaught crash in the log and push it before the process dies. */
    fun installCrashHandler(ctx: Context) {
        val app = ctx.applicationContext
        val previous = Thread.getDefaultUncaughtExceptionHandler()
        if (previous is CrashHandler) return
        Thread.setDefaultUncaughtExceptionHandler(CrashHandler(app, previous))
    }

    private class CrashHandler(val app: Context, val previous: Thread.UncaughtExceptionHandler?) :
        Thread.UncaughtExceptionHandler {
        override fun uncaughtException(t: Thread, e: Throwable) {
            runCatching {
                val trace = StringWriter().also { e.printStackTrace(PrintWriter(it)) }.toString()
                val text = "CRASH on ${t.name}: $trace"
                synchronized(EventLog) {
                    val p = app.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
                    val lines = (p.getString("lines", "")!!.lines() + "${fmt.format(Date())} $text").takeLast(MAX)
                    p.edit().putString("lines", lines.joinToString("\n")).commit()
                }
                push(app, "${fmt.format(Date())} ${redact(text)}\n") // same thread: the process is about to die
            }
            previous?.uncaughtException(t, e)
        }
    }

    private fun ownLogcat(): String = runCatching {
        val p = ProcessBuilder("logcat", "-d", "-v", "time", "--pid=${Process.myPid()}", "-t", "400")
            .redirectErrorStream(true).start()
        p.inputStream.bufferedReader().use { it.readText() }
    }.getOrElse { "logcat unavailable: ${it.message}" }

    /** One TCP connection per message; over Wi-Fi when available so a VPN can't swallow it. Never throws. */
    private fun push(ctx: Context, text: String): Boolean {
        val sink = sink(ctx)
        val host = sink.substringBeforeLast(':').trim()
        val port = sink.substringAfterLast(':', "").trim().toIntOrNull() ?: return false
        if (host.isEmpty()) return false
        return runCatching {
            val factory = runCatching { HomeNetwork.wifiNetwork(ctx)?.socketFactory }.getOrNull()
                ?: SocketFactory.getDefault()
            factory.createSocket().use { s ->
                s.connect(InetSocketAddress(host, port), 2_000)
                s.soTimeout = 3_000
                s.getOutputStream().apply { write(text.toByteArray(Charsets.UTF_8)); flush() }
            }
            true
        }.getOrDefault(false)
    }
}
