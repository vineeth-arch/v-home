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
    @Volatile private var line = "Starting"
    private var activeNetwork: Network? = null
    private var callback: ConnectivityManager.NetworkCallback? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notify.ensureChannel(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action
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
            loop = scope.launch { mainLoop() }
        }
        return START_NOT_STICKY
    }

    override fun onDestroy() {
        callback?.let { runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(it) } }
        callback = null
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
            setLine("Settings problem: ${e.message}")
            stopSelf()
            return
        }
        var attempt = 0
        while (scope.isActive) {
            var cfg = Prefs.load(this)
            val pin = cfg.pin
            val key = cfg.clientKey
            if (pin == null || key == null) { stopSelf(); return }
            val network = HomeNetwork.wifiNetwork(this)
            if (network == null) { stopSelf(); return }
            activeNetwork = network
            val host = Discovery.findTv(
                cfg.host, pin,
                probe = { probePin(it, network.socketFactory) },
                ssdp = { Discovery.ssdpSearch(this, network) },
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
                client.open()
                val r = Runner(
                    watcher, client,
                    persistPaused = { p -> Prefs.save(this, Prefs.load(this).copy(paused = p)); notifyUpdate(p) },
                    clock = { SystemClock.elapsedRealtime() / 1000.0 },
                    status = ::setLine,
                )
                runner = r
                r.session()
                setLine("TV connection closed; reconnecting")
            } catch (e: CancellationException) {
                throw e
            } catch (e: NotPaired) {
                setLine("Pairing lost — open the app and tap Pair")
                stopSelf()
                return
            } catch (e: PinMismatch) {
                setLine("TV certificate does not match the pin")
            } catch (e: Exception) {
                setLine("Connection lost: ${e.message ?: e.javaClass.simpleName}")
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
