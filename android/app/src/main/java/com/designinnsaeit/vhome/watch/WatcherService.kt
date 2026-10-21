package com.designinnsaeit.vhome.watch

import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
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

class WatcherService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var loop: Job? = null
    @Volatile private var runner: Runner? = null
    @Volatile private var watcher: Watcher? = null
    @Volatile private var rearm = true
    @Volatile private var line = "Starting"
    private var activeNetwork: Network? = null
    private var callback: ConnectivityManager.NetworkCallback? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        EventLog.installCrashHandler(this)
        EventLog.add(this, EventLog.header(this))
        Notify.ensureChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
        EventLog.add(this, "service start (${action ?: "watch"}; loop ${if (loop == null) "new" else "running"})")
        if (loop == null && action in SETTINGS_ACTIONS) {
            // From the settings screen while not watching: the activity already saved Prefs. Don't start watching.
            stopSelf(startId)
            return START_NOT_STICKY
        }
        val paused = Prefs.load(this).paused
        startAsForeground(paused)
        when (action) {
            Notify.ACTION_PAUSE -> setPaused(true)
            Notify.ACTION_RESUME -> setPaused(false)
            Notify.ACTION_RELOAD -> watcher?.doubleHomeEscape = Prefs.load(this).doubleHomeEscape
        }
        if (loop == null) {
            registerWifiCallback()
            loop = scope.launch {
                try {
                    mainLoop()
                } catch (e: CancellationException) {
                    throw e
                } catch (e: Throwable) {
                    // Never die silently: the log is how the owner (and we) find out what broke.
                    setLine("Watcher crashed: ${e.javaClass.simpleName}: ${e.message}")
                    stopSelf()
                }
            }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        callback?.let { runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(it) } }
        callback = null
        // Stopped because Wi-Fi went away (or any recoverable reason): arm the job so the next Wi-Fi join
        // starts watching again. Not after "pairing lost" / bad settings, which would just loop.
        if (rearm) WifiJob.arm(this)
        scope.cancel()
        super.onDestroy()
    }

    private fun setPaused(p: Boolean) {
        val r = runner
        if (r != null) {
            if (p) r.pause() else r.resume()
        } else {
            Prefs.save(this, Prefs.load(this).copy(paused = p))
            setLine(if (p) "Paused" else "Watching")
        }
        notifyUpdate(p)
    }

    private fun setLine(s: String) {
        EventLog.add(this, s)
        line = s
        getSharedPreferences(Notify.STATUS_PREFS, MODE_PRIVATE).edit().putString("line", s).apply()
        notifyUpdate(Prefs.load(this).paused)
    }

    private fun notifyUpdate(paused: Boolean) {
        getSystemService(NotificationManager::class.java).notify(ID, buildNotification(paused))
    }

    private fun startAsForeground(paused: Boolean) {
        val n = buildNotification(paused)
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_CONNECTED_DEVICE)
        } else {
            startForeground(ID, n)
        }
    }

    private fun buildNotification(paused: Boolean): Notification {
        val action = if (paused) Notify.ACTION_RESUME else Notify.ACTION_PAUSE
        val pi = PendingIntent.getService(
            this, 0, Intent(this, WatcherService::class.java).setAction(action),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        return Notification.Builder(this, Notify.CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle("Watching TV")
            .setContentText(line)
            .setOngoing(true)
            .addAction(
                Notification.Action.Builder(null, if (paused) "Resume" else "Pause", pi).build(),
            )
            .build()
    }

    private fun registerWifiCallback() {
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onLost(network: Network) {
                if (network == activeNetwork) stopSelf()
            }
        }
        callback = cb
        runCatching { getSystemService(ConnectivityManager::class.java).registerNetworkCallback(HomeNetwork.wifiRequest(), cb) }
    }

    private suspend fun mainLoop() {
        val watcherCfg = Prefs.load(this)
        val watcher = try {
            Watcher(watcherCfg.vhomeId, watcherCfg.homeIds, watcherCfg.doubleHomeEscape)
                .also { it.paused = watcherCfg.paused; this.watcher = it }
        } catch (e: ConfigError) {
            setLine("Settings problem: ${e.message}"); rearm = false
            stopSelf()
            return
        }
        var attempt = 0
        while (scope.isActive) {
            var cfg = Prefs.load(this)
            val pin = cfg.pin
            val key = cfg.clientKey
            if (pin == null || key == null) { setLine("Not paired: open the app and tap Pair"); rearm = false; stopSelf(); return }
            val network = HomeNetwork.wifiNetwork(this)
            if (network == null) { setLine("Not on Wi-Fi: stopped"); stopSelf(); return }
            activeNetwork = network
            setLine("Looking for TV (last known ${cfg.host ?: "none"})")
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
                ssdp = { Discovery.ssdpSearch(this, network).also { EventLog.add(this, "network search found: $it") } },
            )
            if (host == null) {
                setLine("TV not found (off or not home)")
                delay((backoff(attempt++) * 1000).toLong())
                continue
            }
            if (host != cfg.host) { cfg = cfg.copy(host = host); Prefs.save(this, cfg) }
            val client = SsapClient(host, key, pin, false, network.socketFactory, manifest = Prefs.ssapManifest(this))
            val started = SystemClock.elapsedRealtime()
            // Pause/Resume tapped while no runner existed only reached Prefs; bring the watcher in line.
            if (cfg.paused && !watcher.paused) watcher.pause("paused by user")
            else if (!cfg.paused && watcher.paused) watcher.resume()
            try {
                setLine("Connecting to TV at $host")
                client.open()
                EventLog.add(this, "connected; subscribing to TV events")
                val r = Runner(
                    watcher, client,
                    persistPaused = { p -> Prefs.save(this, Prefs.load(this).copy(paused = p)); notifyUpdate(p) },
                    clock = { SystemClock.elapsedRealtime() / 1000.0 },
                    status = ::setLine,
                    log = { EventLog.add(this, it) },
                )
                runner = r
                r.session()
                setLine("TV connection closed; reconnecting")
            } catch (e: CancellationException) {
                throw e
            } catch (e: NotPaired) {
                setLine("Pairing lost — open the app and tap Pair"); rearm = false
                stopSelf()
                return
            } catch (e: PinMismatch) {
                setLine("TV certificate does not match the pin")
            } catch (e: Exception) {
                setLine("Connection lost: ${e.javaClass.simpleName}: ${e.message}")
            } finally {
                runner = null
                client.close()
            }
            if (SystemClock.elapsedRealtime() - started > 30_000) attempt = 0
            delay((backoff(attempt++) * 1000).toLong())
        }
    }

    private companion object {
        const val ID = 1
        val SETTINGS_ACTIONS = setOf(Notify.ACTION_PAUSE, Notify.ACTION_RESUME, Notify.ACTION_RELOAD)
    }
}
