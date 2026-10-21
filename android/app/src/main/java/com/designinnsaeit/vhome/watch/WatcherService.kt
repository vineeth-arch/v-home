package com.designinnsaeit.vhome.watch

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.LinkProperties
import android.net.Network
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import java.net.Inet4Address
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Short notification line per state; "Paused until 10:41 PM" when the pause is timed. */
fun notificationText(
    s: WatchState, pausedUntil: Long? = null,
    time: (Long) -> String = { SimpleDateFormat("h:mm a", Locale.getDefault()).format(Date(it)) },
): String = when (s) {
    WatchState.NOT_PAIRED -> "Not paired yet"
    WatchState.WAITING_WIFI -> "Waiting for home Wi-Fi"
    WatchState.AWAY -> "Not on home Wi-Fi"
    WatchState.LOOKING -> "Looking for your TV"
    WatchState.TV_OFF -> "TV is off"
    WatchState.CONNECTING -> "Connecting to your TV"
    WatchState.WATCHING -> "Watching your TV"
    WatchState.PAUSED ->
        if (pausedUntil == null) "Paused" else "Paused until " + time(pausedUntil)
    WatchState.PROBLEM -> "Needs attention"
}

/** A timed pause is over once its time has passed; no time = until the user resumes. */
fun shouldResume(pausedUntil: Long?, now: Long): Boolean = pausedUntil != null && now >= pausedUntil

/**
 * Long-lived: runs whenever paired and holds the persistent notification. Wi-Fi joining starts [tvJob]
 * (the old watch loop); Wi-Fi loss, "TV not found" and settings errors only end that job, never the service.
 */
class WatcherService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var tvJob: Job? = null
    private var resumeJob: Job? = null
    @Volatile private var runner: Runner? = null
    @Volatile private var watcher: Watcher? = null
    private var tvOffSince: Long? = null   // elapsedRealtime when the TV first stopped answering
    private var lastSearchAt = 0L
    @Volatile private var state = WatchState.WAITING_WIFI
    @Volatile private var activeNetwork: Network? = null
    private val wifiCallback = object : ConnectivityManager.NetworkCallback() {
        override fun onAvailable(network: Network) {
            // A different Wi-Fi (e.g. 2.4 -> 5 GHz) restarts the loop on it; the same one keeps running.
            if (network != activeNetwork) { activeNetwork = network; stopTv() }
            startTv()
        }

        override fun onLost(network: Network) {
            if (network != activeNetwork) return
            activeNetwork = null
            stopTv()
            setState(WatchState.WAITING_WIFI, "Not on Wi-Fi: waiting")
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        running = true
        EventLog.installCrashHandler(this)
        EventLog.add(this, EventLog.header(this))
        Notify.ensureChannel(this)
        state = WatchStatus.read(this).state
        runCatching { getSystemService(ConnectivityManager::class.java).registerNetworkCallback(HomeNetwork.wifiRequest(), wifiCallback) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        EventLog.add(this, "service start (${action ?: "watch"}; loop ${if (tvJob == null) "idle" else "running"})")
        startAsForeground()
        resumeIfDue()
        when (action) {
            Notify.ACTION_PAUSE -> setPaused(true, intent.getIntExtra(WatchStatus.EXTRA_MINUTES, 0))
            Notify.ACTION_RESUME -> setPaused(false)
            Notify.ACTION_RELOAD -> watcher?.doubleHomeEscape = Prefs.load(this).doubleHomeEscape
            WatchStatus.ACTION_RESTART -> { stopTv(); startTv() }
        }
        // Idle until the Wi-Fi callback starts the loop; say why.
        if (tvJob == null) when {
            Prefs.load(this).pin == null -> setState(WatchState.NOT_PAIRED, "Not paired: open the app and tap Pair")
            HomeNetwork.wifiNetwork(this) == null -> setState(WatchState.WAITING_WIFI, "Not on Wi-Fi: waiting")
        }
        return START_STICKY
    }

    override fun onDestroy() {
        running = false
        runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(wifiCallback) }
        // Only reached when Android or the user ends the service: the job brings it back on the next Wi-Fi join.
        WifiJob.arm(this)
        scope.cancel()
        super.onDestroy()
    }

    private fun setState(s: WatchState, line: String) {
        EventLog.add(this, line)
        state = s
        WatchStatus.write(this, s, line)
        notifyUpdate()
    }

    private fun setPaused(p: Boolean, minutes: Int = 0) {
        resumeJob?.cancel(); resumeJob = null
        val until = if (p && minutes > 0) System.currentTimeMillis() + minutes * 60_000L else null
        WatchStatus.setPausedUntil(this, until)
        val r = runner
        if (r != null) {
            if (p) r.pause() else r.resume()
        } else {
            Prefs.save(this, Prefs.load(this).copy(paused = p))
            if (state == WatchState.WATCHING || state == WatchState.PAUSED) {
                setState(if (p) WatchState.PAUSED else WatchState.WATCHING, if (p) "Paused" else "Watching")
            }
        }
        if (until != null) scheduleResume(until)
        notifyUpdate()
    }

    private fun scheduleResume(at: Long) {
        resumeJob = scope.launch {
            delay((at - System.currentTimeMillis()).coerceAtLeast(0))
            resumeJob = null
            setPaused(false)
        }
    }

    /** On any (re)start: a timed pause that ran out while the service was away ends now; one still running is re-timed. */
    private fun resumeIfDue() {
        val until = WatchStatus.pausedUntil(this) ?: return
        if (shouldResume(until, System.currentTimeMillis())) setPaused(false)
        else if (resumeJob == null) scheduleResume(until)
    }

    private fun startTv() {
        synchronized(this) {
            if (tvJob?.isActive == true) return
            val cfg = Prefs.load(this)
            if (cfg.pin == null || cfg.clientKey == null) { setState(WatchState.NOT_PAIRED, "Not paired: open the app and tap Pair"); return }
            val network = activeNetwork ?: HomeNetwork.wifiNetwork(this)
            if (network == null) { setState(WatchState.WAITING_WIFI, "Not on Wi-Fi: waiting"); return }
            activeNetwork = network
            tvJob = scope.launch {
                try {
                    tvLoop(network)
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    // Never die silently: the log is how the owner (and we) find out what broke.
                    setState(WatchState.PROBLEM, "Watcher crashed: ${e.javaClass.simpleName}: ${e.message}")
                }
            }
        }
    }

    private fun stopTv() {
        synchronized(this) {
            tvJob?.cancel(); tvJob = null
            runner = null; watcher = null
        }
    }

    private fun notifyUpdate() {
        getSystemService(NotificationManager::class.java).notify(ID, buildNotification())
    }

    private fun startAsForeground() {
        val n = buildNotification()
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(ID, n)
        }
    }

    private fun buildNotification(): Notification {
        val paused = Prefs.load(this).paused
        val flags = PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), flags)
        val act = Intent(this, WatcherService::class.java).setAction(if (paused) Notify.ACTION_RESUME else Notify.ACTION_PAUSE)
        if (!paused) act.putExtra(WatchStatus.EXTRA_MINUTES, 60)
        val pi = PendingIntent.getService(this, 0, act, flags)
        val s = state
        val big = explain(s) + WatchStatus.redirectsToday(this).takeIf { s == WatchState.WATCHING && it > 0 }
            ?.let { "\n$it Home presses redirected today" }.orEmpty()
        return Notification.Builder(this, Notify.CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_watch)
            .setContentTitle("V/HOME Watcher")
            // the phone's own 12/24 h setting, same as the app screen
            .setContentText(notificationText(s, WatchStatus.pausedUntil(this)) { android.text.format.DateFormat.getTimeFormat(this).format(Date(it)) })
            .setStyle(Notification.BigTextStyle().bigText(big))
            .setContentIntent(open)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setOngoing(true)
            .addAction(Notification.Action.Builder(null, if (paused) "Resume" else "Pause 1 h", pi).build())
            .build()
    }

    /** Gateway + prefix of the Wi-Fi's IPv4 setup: stands in for "is this my home router" without a location permission. */
    private fun fingerprint(lp: LinkProperties?): String? {
        val gw = lp?.routes?.firstOrNull { it.isDefaultRoute && it.gateway is Inet4Address }?.gateway?.hostAddress ?: return null
        val prefix = lp.linkAddresses.firstOrNull { it.address is Inet4Address }?.prefixLength ?: return null
        return "$gw/$prefix"
    }

    private suspend fun tvLoop(network: Network) {
        val watcherCfg = Prefs.load(this)
        val watcher = try {
            Watcher(watcherCfg.vhomeId, watcherCfg.homeIds, watcherCfg.doubleHomeEscape)
                .also { it.paused = watcherCfg.paused; this.watcher = it }
        } catch (e: ConfigError) {
            setState(WatchState.PROBLEM, "Settings problem: ${e.message}")
            return
        }
        val homePrefs = getSharedPreferences("vhome_watch_home", MODE_PRIVATE)
        val fp = fingerprint(getSystemService(ConnectivityManager::class.java).getLinkProperties(network))
        tvOffSince = null; lastSearchAt = 0L
        var attempt = 0
        while (scope.isActive) {
            var cfg = Prefs.load(this)
            val pin = cfg.pin
            val key = cfg.clientKey
            if (pin == null || key == null) { setState(WatchState.NOT_PAIRED, "Pairing lost: open the app and tap Pair"); return }
            setState(WatchState.LOOKING, "Looking for TV (last known ${cfg.host ?: "none"})")
            val host = Discovery.findTv(
                cfg.host, pin,
                probe = { h ->
                    probePin(h, network.socketFactory).also {
                        EventLog.add(this, "probe $h: " + when {
                            it == null -> "no answer on port $PORT"
                            it.equals(pin, ignoreCase = true) -> "certificate matches"
                            else -> "different certificate"
                        })
                    }
                },
                ssdp = {
                    // The saved IP is retried every few seconds; a full network search (multicast) at most every 2 min.
                    val now = SystemClock.elapsedRealtime()
                    if (now - lastSearchAt < 120_000) emptyList()
                    else { lastSearchAt = now; Discovery.ssdpSearch(this, network).also { EventLog.add(this, "network search found: $it") } }
                },
            )
            if (host == null) {
                // Never-seen fingerprint (fresh install or first run of this build) counts as home: an already-paired
                // phone at home with the TV off must keep retrying, not go AWAY until the TV happens to be seen once.
                val known = homePrefs.getString("fp", null)
                if (known != null && (fp == null || known != fp)) {
                    // Not a Wi-Fi we know the TV on: one attempt was enough. Idle (no timers) until the Wi-Fi changes.
                    setState(WatchState.AWAY, "Not on home Wi-Fi ($fp): TV not found, not retrying")
                    return
                }
                if (tvOffSince == null) tvOffSince = SystemClock.elapsedRealtime()
                setState(WatchState.TV_OFF, "TV not found (off or not home)")
                delay((backoff(attempt++) * 1000).toLong())
                continue
            }
            if (fp != null && homePrefs.getString("fp", null) != fp) homePrefs.edit().putString("fp", fp).apply()
            if (host != cfg.host) { cfg = cfg.copy(host = host); Prefs.save(this, cfg) }
            val client = SsapClient(host, key, pin, false, network.socketFactory, manifest = Prefs.ssapManifest(this))
            val started = SystemClock.elapsedRealtime()
            var r: Runner? = null
            // Pause/Resume tapped while no runner existed only reached Prefs; bring the watcher in line.
            if (cfg.paused && !watcher.paused) watcher.pause("paused by user")
            else if (!cfg.paused && watcher.paused) watcher.resume()
            try {
                setState(WatchState.CONNECTING, "Connecting to TV at $host")
                client.open()
                // TV unreachable for 20 s+ and now answering = it was just switched on (not a phone-side blip).
                val boot = tvOffSince?.let { SystemClock.elapsedRealtime() - it >= 20_000 } == true
                tvOffSince = null
                EventLog.add(this, "connected; subscribing to TV events" + if (boot) " (TV was off: switch-on)" else "")
                r = Runner(
                    watcher, client,
                    persistPaused = { p -> Prefs.save(this, Prefs.load(this).copy(paused = p)); notifyUpdate() },
                    clock = { SystemClock.elapsedRealtime() / 1000.0 },
                    status = { setState(if (watcher.paused) WatchState.PAUSED else WatchState.WATCHING, it) },
                    log = { EventLog.add(this, it) },
                    bootSession = boot,
                    onRedirect = { WatchStatus.redirected(this, it) },
                )
                runner = r
                r.session()
                setState(WatchState.LOOKING, "TV connection closed; reconnecting")
            } catch (e: CancellationException) {
                throw e
            } catch (e: NotPaired) {
                setState(WatchState.NOT_PAIRED, "Pairing lost: open the app and tap Pair")
                return
            } catch (e: PinMismatch) {
                setState(WatchState.PROBLEM, "TV certificate does not match the pin")
            } catch (e: Exception) {
                // Could not connect at all (vs. a session that ran): the TV may be booting or off.
                if (r == null && tvOffSince == null) tvOffSince = started
                setState(WatchState.LOOKING, "Connection lost: ${e.javaClass.simpleName}: ${e.message}")
            } finally {
                if (runner === r) runner = null
                client.close()
            }
            if (SystemClock.elapsedRealtime() - started > 30_000) attempt = 0
            delay((backoff(attempt++) * 1000).toLong())
        }
    }

    companion object {
        private const val ID = 1
        /** True between onCreate and onDestroy; the watchdog job reads it. */
        @Volatile var running = false
    }
}
