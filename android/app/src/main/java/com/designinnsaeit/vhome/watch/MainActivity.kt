package com.designinnsaeit.vhome.watch

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.widget.Toast
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.provider.Settings
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.Switch
import android.widget.TextView
import javax.net.SocketFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : Activity() {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private lateinit var status: TextView
    private lateinit var pauseToggle: Button
    private lateinit var hostField: EditText
    private lateinit var vhomeField: EditText
    private lateinit var doubleHomeSwitch: Switch
    private lateinit var homeIdsField: EditText
    private lateinit var pairStatus: TextView
    private lateinit var batteryText: TextView
    private lateinit var notifText: TextView
    private lateinit var notifButton: Button
    private lateinit var logText: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        HomeNetwork.register(this)
        Notify.ensureChannel(this)

        status = findViewById(R.id.status)
        pauseToggle = findViewById(R.id.pauseToggle)
        hostField = findViewById(R.id.hostField)
        vhomeField = findViewById(R.id.vhomeField)
        homeIdsField = findViewById(R.id.homeIdsField)
        pairStatus = findViewById(R.id.pairStatus)
        batteryText = findViewById(R.id.batteryText)
        notifText = findViewById(R.id.notifText)
        notifButton = findViewById(R.id.notifButton)

        val c = Prefs.load(this)
        hostField.setText(c.host ?: "")
        vhomeField.setText(c.vhomeId)
        homeIdsField.setText(c.homeIds.joinToString(", "))
        doubleHomeSwitch = findViewById(R.id.doubleHomeSwitch)
        doubleHomeSwitch.isChecked = c.doubleHomeEscape
        doubleHomeSwitch.setOnCheckedChangeListener { _, _ -> save() }

        findViewById<Button>(R.id.saveButton).setOnClickListener { save(); pairStatus.setText(R.string.saved) }
        findViewById<Button>(R.id.pairButton).setOnClickListener { pair() }
        findViewById<Button>(R.id.batteryButton).setOnClickListener {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
            )
        }
        notifButton.setOnClickListener { requestNotifications() }
        pauseToggle.setOnClickListener { togglePause() }
        logText = findViewById(R.id.logText)
        findViewById<Button>(R.id.startButton).setOnClickListener { startWatchingIfReady(fromButton = true) }
        findViewById<Button>(R.id.testButton).setOnClickListener { testTv() }
        findViewById<Button>(R.id.copyLogButton).setOnClickListener { copyLog() }
        findViewById<Button>(R.id.refreshLogButton).setOnClickListener { refreshLog() }

        if (Build.VERSION.SDK_INT < 33) {
            notifText.visibility = View.GONE
            notifButton.visibility = View.GONE
        } else if (!notificationsGranted()) {
            requestNotifications()
        }
    }

    /**
     * The Wi-Fi trigger only fires when the phone joins a network, so pairing or opening the app while
     * already on home Wi-Fi must start watching itself. A visible activity may start a foreground service;
     * repeat starts are harmless (the service runs its loop once).
     */
    private fun startWatchingIfReady(fromButton: Boolean = false) {
        val why = when {
            Prefs.load(this).pin == null -> "not paired yet"
            HomeNetwork.wifiNetwork(this) == null -> "phone not on Wi-Fi"
            else -> null
        }
        if (why != null) {
            if (fromButton) EventLog.add(this, "Start watching skipped: $why")
            refreshLog()
            return
        }
        runCatching { startForegroundService(Intent(this, WatcherService::class.java)) }
            .onFailure { EventLog.add(this, "could not start watcher: ${it.javaClass.simpleName}: ${it.message}") }
        refreshLog()
    }

    private fun refreshLog() {
        val log = EventLog.read(this)
        logText.text = log.ifEmpty { getString(R.string.log_empty) }
        status.text = getSharedPreferences(Notify.STATUS_PREFS, MODE_PRIVATE)
            .getString("line", null) ?: getString(R.string.status_default)
    }

    private fun copyLog() {
        val c = Prefs.load(this)
        val header = "V/HOME Watcher ${packageManager.getPackageInfo(packageName, 0).versionName} · " +
            "Android ${Build.VERSION.RELEASE} (${Build.MANUFACTURER} ${Build.MODEL}) · host ${c.host} · " +
            "paired ${c.pin != null} · paused ${c.paused} · home ids ${c.homeIds}\n"
        getSystemService(ClipboardManager::class.java)
            .setPrimaryClip(ClipData.newPlainText("V/HOME log", header + EventLog.read(this)))
        Toast.makeText(this, R.string.log_copied, Toast.LENGTH_SHORT).show()
    }

    /** Probe the saved TV on this Wi-Fi and say plainly whether it answers and is the paired one. */
    private fun testTv() {
        val c = Prefs.load(this)
        val host = hostField.text.toString().trim().ifEmpty { c.host ?: "" }
        val pin = c.pin
        val network = HomeNetwork.wifiNetwork(this)
        when {
            pin == null -> { pairStatus.setText(R.string.test_not_paired); return }
            network == null -> { pairStatus.setText(R.string.test_no_wifi); return }
            host.isEmpty() -> { pairStatus.setText(R.string.need_ip); return }
        }
        pairStatus.setText(R.string.testing)
        scope.launch {
            val got = withContext(Dispatchers.IO) { probePin(host, network!!.socketFactory) }
            val msg = when {
                got == null -> getString(R.string.test_no_answer, host)
                got.equals(pin, ignoreCase = true) -> getString(R.string.test_match, host)
                else -> getString(R.string.test_mismatch, host)
            }
            pairStatus.text = msg
            EventLog.add(this@MainActivity, "Test TV: $msg")
            refreshLog()
        }
    }

    override fun onResume() {
        super.onResume()
        startWatchingIfReady()
        refreshPause()
        val unrestricted = getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)
        batteryText.setText(if (unrestricted) R.string.battery_ok else R.string.battery_restricted)
        refreshNotifications()
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, results: IntArray) {
        refreshNotifications()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    private fun currentConfig(): Config {
        val ids = homeIdsField.text.toString().split(',').map { it.trim() }.filter { it.isNotEmpty() }
        return Prefs.load(this).copy(
            host = hostField.text.toString().trim().ifEmpty { null },
            vhomeId = vhomeField.text.toString().trim().ifEmpty { DEFAULT_VHOME_ID },
            homeIds = ids.ifEmpty { DEFAULT_HOME_IDS },
            doubleHomeEscape = doubleHomeSwitch.isChecked,
        )
    }

    private fun save() {
        Prefs.save(this, currentConfig())
        // Tell a running service to pick up live settings; harmless if it isn't running.
        runCatching { startService(Intent(this, WatcherService::class.java).setAction(Notify.ACTION_RELOAD)) }
    }

    private fun pair() {
        val host = hostField.text.toString().trim()
        if (host.isEmpty()) {
            pairStatus.setText(R.string.need_ip)
            return
        }
        pairStatus.setText(R.string.pair_prompt)
        scope.launch {
            try {
                val (key, pin) = withContext(Dispatchers.IO) {
                    val sockets = HomeNetwork.wifiNetwork(this@MainActivity)?.socketFactory ?: SocketFactory.getDefault()
                    val client = SsapClient(host, null, null, true, sockets,
                        manifest = Prefs.ssapManifest(this@MainActivity))
                    try {
                        val key = client.open()
                        key to client.certSha256!!
                    } finally {
                        client.close()
                    }
                }
                Prefs.save(this@MainActivity, applyPairing(currentConfig(), host, key, pin))
                pairStatus.text = getString(R.string.paired_with, host)
                startWatchingIfReady()
            } catch (e: Exception) {
                pairStatus.text = e.message?.let { getString(R.string.pair_failed, it) }
                    ?: getString(R.string.pair_failed_unknown)
            }
        }
    }

    private fun refreshPause() {
        pauseToggle.setText(if (Prefs.load(this).paused) R.string.resume else R.string.pause)
    }

    private fun togglePause() {
        val c = Prefs.load(this)
        Prefs.save(this, c.copy(paused = !c.paused))
        val action = if (c.paused) Notify.ACTION_RESUME else Notify.ACTION_PAUSE
        try {
            startService(Intent(this, WatcherService::class.java).setAction(action))
        } catch (e: RuntimeException) {
            // Service not running; it reads the saved flag when it starts.
        }
        refreshPause()
    }

    private fun notificationsGranted() =
        Build.VERSION.SDK_INT < 33 ||
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun requestNotifications() {
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
    }

    private fun refreshNotifications() {
        if (Build.VERSION.SDK_INT < 33) return
        val ok = notificationsGranted()
        notifText.setText(if (ok) R.string.notif_ok else R.string.notif_off)
        notifButton.visibility = if (ok) View.GONE else View.VISIBLE
    }
}
