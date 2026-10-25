package com.designinnsaeit.vhome.watch

import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.os.Build

/**
 * Starts watching when the phone is on Wi-Fi. Found on the owner's Samsung (Android 14): the
 * network-callback PendingIntent is dropped as soon as the app leaves the screen, so it can't be the
 * only trigger. A persisted job with a Wi-Fi network requirement survives that and reboots. It runs
 * once per arm; WatcherService re-arms it when it stops because Wi-Fi was lost.
 */
class WifiJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        if (Prefs.mode(this) == ControllerMode.VNODE || Prefs.load(this).pin == null) return false
        EventLog.add(this, "Wi-Fi job: on Wi-Fi, starting watcher")
        startWatcher(this, "Wi-Fi job")
        return false
    }

    override fun onStopJob(params: JobParameters): Boolean = false

    companion object {
        private const val ID = 7001

        fun arm(ctx: Context) {
            val b = JobInfo.Builder(ID, ComponentName(ctx, WifiJob::class.java)).setPersisted(true)
            // Require Wi-Fi itself: "unmetered" alone can match unlimited mobile data and loop.
            if (Build.VERSION.SDK_INT >= 28) b.setRequiredNetwork(HomeNetwork.wifiRequest())
            else b.setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
            runCatching { ctx.getSystemService(JobScheduler::class.java).schedule(b.build()) }
                .onFailure { EventLog.add(ctx, "could not arm Wi-Fi job: ${it.message}") }
        }
    }
}

/** Safety net: every 15 min, if paired and the service is gone (killed, swiped, never restarted), start it. */
class WatchdogJob : JobService() {
    override fun onStartJob(params: JobParameters): Boolean {
        if (Prefs.mode(this) == ControllerMode.STANDALONE && Prefs.load(this).pin != null && !WatcherService.running) {
            EventLog.add(this, "watchdog: service not running, starting it")
            startWatcher(this, "watchdog")
        }
        return false
    }

    override fun onStopJob(params: JobParameters): Boolean = false

    companion object {
        private const val ID = 7002

        fun arm(ctx: Context) {
            val b = JobInfo.Builder(ID, ComponentName(ctx, WatchdogJob::class.java))
                .setPersisted(true).setPeriodic(15 * 60_000L)
            runCatching { ctx.getSystemService(JobScheduler::class.java).schedule(b.build()) }
                .onFailure { EventLog.add(ctx, "could not arm watchdog job: ${it.message}") }
        }
    }
}
