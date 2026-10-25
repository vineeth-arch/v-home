package com.designinnsaeit.vhome.watch

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.job.JobInfo
import android.app.job.JobParameters
import android.app.job.JobScheduler
import android.app.job.JobService
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import java.net.Inet4Address
import java.net.InetAddress
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import okhttp3.Dns

/**
 * Tells the owner about node problems while the app is closed. Every 15 min (the platform minimum), on Wi-Fi
 * only, fetch /v1/health and post one notification when the set of errors is new. No service, no wake lock.
 * Decisions live in [NodeHealthUi.shouldAlert].
 */
class NodeHealthJob : JobService() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var running: Job? = null

    override fun onStartJob(params: JobParameters): Boolean {
        val store = NodeStore(this)
        if (Prefs.mode(this) != ControllerMode.VNODE || !store.isPaired()) { cancel(this); return false }
        val net = HomeNetwork.wifiNetwork(this) ?: return false // away from Wi-Fi: nothing to check
        running = scope.launch {
            try { check(store, net) } finally { jobFinished(params, false) }
        }
        return true
    }

    override fun onStopJob(params: JobParameters): Boolean { running?.cancel(); return false }

    private suspend fun check(store: NodeStore, net: Network) {
        val prefs = getSharedPreferences(PREFS, MODE_PRIVATE)
        val fp = fingerprint(net, this)
        val health = try {
            val dns = object : Dns {
                override fun lookup(hostname: String): List<InetAddress> =
                    runCatching { net.getAllByName(hostname).toList() }.getOrElse { Dns.SYSTEM.lookup(hostname) }
            }
            NodeClient(store.host!!, store.nodeId, false, net.socketFactory, store.token(), dns = dns, callTimeoutS = 10).health()
        } catch (e: NodeException) {
            null
        }
        val sameWifi = fp != null && fp == prefs.getString(KEY_FP, null)
        var streak = prefs.getInt(KEY_STREAK, 0)
        if (health != null) {
            streak = 0
            if (fp != null) prefs.edit().putString(KEY_FP, fp).apply()
        } else if (sameWifi) streak++ else streak = 0
        prefs.edit().putInt(KEY_STREAK, streak).apply()

        val previous = prefs.getStringSet(KEY_KEYS, emptySet()).orEmpty().toSet()
        when (val d = NodeHealthUi.shouldAlert(previous, health, streak, sameWifi)) {
            NodeHealthUi.AlertDecision.None -> {}
            NodeHealthUi.AlertDecision.Clear -> {
                getSystemService(NotificationManager::class.java).cancel(NOTE_ID)
                prefs.edit().putStringSet(KEY_KEYS, emptySet()).apply()
            }
            is NodeHealthUi.AlertDecision.Post ->
                // Without the permission nothing is recorded, so the alert still comes once it is granted.
                if (post(this, d.text)) prefs.edit().putStringSet(KEY_KEYS, d.keys).apply()
        }
    }

    companion object {
        private const val ID = 7003
        private const val NOTE_ID = 3
        const val CHANNEL = "node_problems"
        private const val PREFS = "vhome_node_health"
        private const val KEY_KEYS = "alerted_keys"
        private const val KEY_STREAK = "unreachable_streak"
        private const val KEY_FP = "wifi_fp"

        /** Idempotent: an already scheduled job keeps its period. */
        fun schedule(ctx: Context) {
            val js = ctx.getSystemService(JobScheduler::class.java)
            if (js.getPendingJob(ID) != null) return
            val b = JobInfo.Builder(ID, ComponentName(ctx, NodeHealthJob::class.java))
                .setPersisted(true).setPeriodic(15 * 60_000L)
            if (Build.VERSION.SDK_INT >= 28) b.setRequiredNetwork(HomeNetwork.wifiRequest())
            else b.setRequiredNetworkType(JobInfo.NETWORK_TYPE_UNMETERED)
            runCatching { js.schedule(b.build()) }
                .onFailure { EventLog.add(ctx, "could not schedule node health job: ${it.message}") }
        }

        /** Leaving VNODE mode or forgetting the node: stop checking and drop the alert and its memory. */
        fun cancel(ctx: Context) {
            runCatching { ctx.getSystemService(JobScheduler::class.java).cancel(ID) }
            ctx.getSystemService(NotificationManager::class.java).cancel(NOTE_ID)
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()
        }

        /** Called when the app reached the node: this Wi-Fi is the one it lives on. */
        fun rememberWifi(ctx: Context) {
            val net = HomeNetwork.wifiNetwork(ctx) ?: return
            fingerprint(net, ctx)?.let { ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(KEY_FP, it).apply() }
        }

        /** Gateway + prefix of the Wi-Fi's IPv4 setup, as WatcherService does: "is this my home router" without a location permission. */
        private fun fingerprint(net: Network, ctx: Context): String? {
            val lp = ctx.getSystemService(ConnectivityManager::class.java).getLinkProperties(net)
            val gw = lp?.routes?.firstOrNull { it.isDefaultRoute && it.gateway is Inet4Address }?.gateway?.hostAddress ?: return null
            val prefix = lp.linkAddresses.firstOrNull { it.address is Inet4Address }?.prefixLength ?: return null
            return "$gw/$prefix"
        }

        private fun post(ctx: Context, text: String): Boolean {
            if (Build.VERSION.SDK_INT >= 33 &&
                ctx.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
            ) return false
            val nm = ctx.getSystemService(NotificationManager::class.java)
            nm.createNotificationChannel(
                NotificationChannel(CHANNEL, ctx.getString(R.string.channel_node_problems), NotificationManager.IMPORTANCE_DEFAULT),
            )
            val open = PendingIntent.getActivity(
                ctx, 0, Intent(ctx, NodeActivity::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
            )
            val n = Notification.Builder(ctx, CHANNEL)
                .setSmallIcon(R.drawable.ic_stat_watch)
                .setContentTitle(ctx.getString(R.string.node_alert_title))
                .setContentText(text)
                .setContentIntent(open)
                .setAutoCancel(true)
                .build()
            nm.notify(NOTE_ID, n)
            return true
        }
    }
}
