package com.designinnsaeit.vhome.watch

import android.Manifest
import android.app.Activity
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
    private lateinit var homeIdsField: EditText
    private lateinit var pairStatus: TextView
    private lateinit var batteryText: TextView
    private lateinit var notifText: TextView
    private lateinit var notifButton: Button

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

        findViewById<Button>(R.id.saveButton).setOnClickListener { save(); pairStatus.setText(R.string.saved) }
        findViewById<Button>(R.id.pairButton).setOnClickListener { pair() }
        findViewById<Button>(R.id.batteryButton).setOnClickListener {
            startActivity(
                Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
            )
        }
        notifButton.setOnClickListener { requestNotifications() }
        pauseToggle.setOnClickListener { togglePause() }

        if (Build.VERSION.SDK_INT < 33) {
            notifText.visibility = View.GONE
            notifButton.visibility = View.GONE
        } else if (!notificationsGranted()) {
            requestNotifications()
        }
    }

    override fun onResume() {
        super.onResume()
        status.text = getSharedPreferences(Notify.STATUS_PREFS, MODE_PRIVATE)
            .getString("line", null) ?: getString(R.string.status_default)
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
        )
    }

    private fun save() = Prefs.save(this, currentConfig())

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
                    val client = SsapClient(host, null, null, true, SocketFactory.getDefault())
                    try {
                        val key = client.open()
                        key to client.certSha256!!
                    } finally {
                        client.close()
                    }
                }
                Prefs.save(this@MainActivity, applyPairing(currentConfig(), host, key, pin))
                pairStatus.text = getString(R.string.paired_with, host)
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
