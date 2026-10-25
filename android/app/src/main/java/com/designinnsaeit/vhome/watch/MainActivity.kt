package com.designinnsaeit.vhome.watch

import android.Manifest
import android.app.Activity
import android.app.ActivityManager
import android.app.NotificationManager
import android.app.usage.UsageStatsManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.format.DateFormat
import android.text.format.DateUtils
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.ImageView
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast
import java.util.Date
import javax.net.SocketFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

class MainActivity : Activity() {
    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())

    private lateinit var scroll: ScrollView
    private lateinit var content: View
    private lateinit var hostField: EditText
    private lateinit var stepHostField: EditText
    private lateinit var vhomeField: EditText
    private lateinit var homeIdsField: EditText
    private lateinit var doubleHomeSwitch: Switch
    private lateinit var stepResult: TextView
    private lateinit var tvResult: TextView
    private lateinit var logText: TextView
    private lateinit var pauseChoices: View
    private var setupExpanded = false
    private var advancedOpen = false

    // Prefs hold listeners weakly, so keep a strong reference for as long as it is registered.
    private val statusListener = SharedPreferences.OnSharedPreferenceChangeListener { _, _ -> render() }

    private enum class Mark { OK, BAD, GUIDED }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        if (Prefs.mode(this) == ControllerMode.VNODE) {
            // The node watches; this screen is only for standalone mode.
            startActivity(Intent(this, NodeActivity::class.java))
            finish()
            return
        }
        EventLog.installCrashHandler(this)
        setContentView(R.layout.activity_main)
        HomeNetwork.register(this)
        Notify.ensureChannel(this)

        scroll = findViewById(R.id.scroll)
        content = findViewById(R.id.content)
        hostField = findViewById(R.id.hostField)
        stepHostField = findViewById(R.id.stepHostField)
        vhomeField = findViewById(R.id.vhomeField)
        homeIdsField = findViewById(R.id.homeIdsField)
        stepResult = findViewById(R.id.stepResult)
        tvResult = findViewById(R.id.tvResult)
        logText = findViewById(R.id.logText)
        pauseChoices = findViewById(R.id.pauseChoices)

        val c = Prefs.load(this)
        hostField.setText(c.host ?: "")
        stepHostField.setText(c.host ?: "")
        vhomeField.setText(c.vhomeId)
        homeIdsField.setText(c.homeIds.joinToString(", "))
        doubleHomeSwitch = findViewById(R.id.doubleHomeSwitch)
        doubleHomeSwitch.isChecked = c.doubleHomeEscape
        doubleHomeSwitch.setOnCheckedChangeListener { _, _ -> save() }

        findViewById<Button>(R.id.controllerButton).setOnClickListener {
            startActivity(Intent(this, NodeActivity::class.java).apply {
                if (NodeStore(this@MainActivity).isPaired()) putExtra(NodeActivity.EXTRA_ENABLE, true)
            })
        }
        findViewById<Button>(R.id.stepPairButton).setOnClickListener { pair(stepHostField, stepResult) }
        findViewById<Button>(R.id.pairButton).setOnClickListener { pair(hostField, tvResult) }
        findViewById<Button>(R.id.testButton).setOnClickListener { testTv() }
        findViewById<Button>(R.id.openTvButton).setOnClickListener { openOnTv() }
        findViewById<Button>(R.id.editIpButton).setOnClickListener {
            val edit = findViewById<View>(R.id.ipEdit)
            edit.visibility = if (edit.visibility == View.VISIBLE) View.GONE else View.VISIBLE
            if (edit.visibility == View.VISIBLE) hostField.requestFocus()
        }
        findViewById<Button>(R.id.pauseButton).setOnClickListener {
            pauseChoices.visibility = if (pauseChoices.visibility == View.VISIBLE) View.GONE else View.VISIBLE
        }
        findViewById<Button>(R.id.pause30).setOnClickListener { pause(30) }
        findViewById<Button>(R.id.pause60).setOnClickListener { pause(60) }
        findViewById<Button>(R.id.pause120).setOnClickListener { pause(120) }
        findViewById<Button>(R.id.pauseOpen).setOnClickListener { pause(0) }
        findViewById<Button>(R.id.saveButton).setOnClickListener {
            save()
            result(findViewById(R.id.savedText), true, getString(R.string.saved))
        }
        findViewById<View>(R.id.advancedHeader).setOnClickListener {
            advancedOpen = !advancedOpen
            findViewById<View>(R.id.advancedBody).visibility = if (advancedOpen) View.VISIBLE else View.GONE
            findViewById<TextView>(R.id.advancedToggle).setText(if (advancedOpen) R.string.hide else R.string.show)
            if (advancedOpen) refreshLog()
        }
        findViewById<Button>(R.id.copyLogButton).setOnClickListener { copyLog() }
        val sinkField = findViewById<EditText>(R.id.sinkField)
        sinkField.setText(EventLog.sink(this))
        findViewById<Button>(R.id.sendLogButton).setOnClickListener {
            EventLog.setSink(this, sinkField.text.toString())
            EventLog.sendFullDump(this) { ok ->
                runOnUiThread {
                    Toast.makeText(this, if (ok) R.string.log_sent else R.string.log_send_failed, Toast.LENGTH_LONG).show()
                }
            }
        }

        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)
        }
    }

    override fun onResume() {
        super.onResume()
        startWatching()
        getSharedPreferences(WatchStatus.PREFS, MODE_PRIVATE).registerOnSharedPreferenceChangeListener(statusListener)
        render()
    }

    override fun onPause() {
        getSharedPreferences(WatchStatus.PREFS, MODE_PRIVATE).unregisterOnSharedPreferenceChangeListener(statusListener)
        super.onPause()
    }

    override fun onRequestPermissionsResult(code: Int, perms: Array<out String>, results: IntArray) {
        render()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    /** The service runs whenever paired (it owns the persistent notification); repeat starts are harmless. */
    private fun startWatching() {
        if (Prefs.load(this).pin == null) return
        runCatching { startForegroundService(Intent(this, WatcherService::class.java)) }
            .onFailure { EventLog.add(this, "could not start watcher: ${it.javaClass.simpleName}: ${it.message}") }
    }

    // ---- Rendering -------------------------------------------------------------------------------

    private fun render() {
        val c = Prefs.load(this)
        val paired = c.pin != null
        val until = WatchStatus.pausedUntil(this)
        val paused = c.paused && (until == null || until > System.currentTimeMillis())
        val s = WatchStatus.read(this)
        val state = when {
            !paired -> WatchState.NOT_PAIRED
            paused -> WatchState.PAUSED
            else -> s.state
        }
        findViewById<View>(R.id.firstRun).visibility = if (paired) View.GONE else View.VISIBLE
        findViewById<View>(R.id.hero).visibility = if (paired) View.VISIBLE else View.GONE
        findViewById<View>(R.id.tvSection).visibility = if (paired) View.VISIBLE else View.GONE
        findViewById<TextView>(R.id.firstExplain).text = explain(WatchState.NOT_PAIRED)

        val firstIssue = renderSetup(paired)
        if (paired) renderHero(state, s, firstIssue)
        renderTv(c)
        if (advancedOpen) refreshLog()
    }

    private fun renderHero(state: WatchState, s: Status, firstIssue: View?) {
        val (bg, fg) = when (state) {
            WatchState.WATCHING -> R.color.blue to R.color.on_blue
            WatchState.PAUSED -> R.color.grey to R.color.ink
            WatchState.PROBLEM, WatchState.NOT_PAIRED -> R.color.red to R.color.on_colour
            else -> R.color.yellow to R.color.on_colour
        }
        findViewById<View>(R.id.heroBlock).setBackgroundColor(getColor(bg))
        findViewById<TextView>(R.id.heroTitle).apply { setText(title(state)); setTextColor(getColor(fg)) }
        findViewById<TextView>(R.id.heroDetail).apply { text = detail(state, s); setTextColor(getColor(fg)) }
        findViewById<TextView>(R.id.heroExplain).text = explain(state)
        findViewById<TextView>(R.id.countValue).text = WatchStatus.redirectsToday(this).toString()
        findViewById<TextView>(R.id.countLabel).setText(R.string.count_label)

        val primary = findViewById<Button>(R.id.primaryButton)
        val pauseButton = findViewById<Button>(R.id.pauseButton)
        when {
            state == WatchState.PAUSED -> {
                primary.visibility = View.VISIBLE
                primary.setText(R.string.resume)
                primary.setOnClickListener { resume() }
                pauseButton.visibility = View.GONE
                pauseChoices.visibility = View.GONE
            }
            firstIssue != null -> {
                primary.visibility = View.VISIBLE
                primary.setText(R.string.fix_it)
                primary.setOnClickListener { scrollTo(firstIssue) }
                pauseButton.visibility = View.VISIBLE
            }
            else -> {
                primary.visibility = View.GONE
                pauseButton.visibility = View.VISIBLE
            }
        }
    }

    private fun title(state: WatchState) = when (state) {
        WatchState.WATCHING -> R.string.title_watching
        WatchState.WAITING_WIFI -> R.string.title_waiting_wifi
        WatchState.AWAY -> R.string.title_away
        WatchState.LOOKING -> R.string.title_looking
        WatchState.TV_OFF -> R.string.title_tv_off
        WatchState.CONNECTING -> R.string.title_connecting
        WatchState.PAUSED -> R.string.title_paused
        WatchState.NOT_PAIRED -> R.string.title_not_paired
        WatchState.PROBLEM -> R.string.title_problem
    }

    private fun detail(state: WatchState, s: Status): String {
        val time = DateFormat.getTimeFormat(this)
        val now = System.currentTimeMillis()
        val at = s.lastRedirectAt
        val secs = s.lastRedirectS
        return when {
            state == WatchState.PAUSED -> WatchStatus.pausedUntil(this)
                ?.let { getString(R.string.paused_until, time.format(Date(it))) } ?: getString(R.string.paused_open)
            state == WatchState.WATCHING && at != null && secs != null -> {
                val ago = if (now - at < DateUtils.MINUTE_IN_MILLIS) getString(R.string.just_now)
                else DateUtils.getRelativeTimeSpanString(at, now, DateUtils.MINUTE_IN_MILLIS).toString()
                getString(R.string.last_redirect, String.format("%.1f", secs), ago)
            }
            state == WatchState.PROBLEM && s.line.isNotEmpty() -> s.line
            s.since > 0 -> getString(R.string.since, time.format(Date(s.since)))
            else -> ""
        }
    }

    /** Fills the checklist and returns the first detected row that needs fixing (the hero's "Fix it" target). */
    private fun renderSetup(paired: Boolean): View? {
        val notif = getSystemService(NotificationManager::class.java).areNotificationsEnabled()
        val battery = getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName)
        val modern = Build.VERSION.SDK_INT >= 28
        val background = !modern || !getSystemService(ActivityManager::class.java).isBackgroundRestricted
        // RARE (40) and RESTRICTED (45) mean Android or Samsung is holding the app back.
        val bucket = !modern ||
            getSystemService(UsageStatsManager::class.java).appStandbyBucket < UsageStatsManager.STANDBY_BUCKET_RARE

        val bad = listOfNotNull(
            row(R.id.rowPaired, paired, R.string.row_paired, R.string.row_paired_why) {
                scrollTo(stepHostField)
                stepHostField.requestFocus()
            },
            row(R.id.rowNotif, notif, R.string.row_notif, R.string.row_notif_why) {
                openFirst(
                    Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(Settings.EXTRA_APP_PACKAGE, packageName),
                    appDetails(),
                )
            },
            row(R.id.rowBattery, battery, R.string.row_battery, R.string.row_battery_why) {
                openFirst(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")),
                    appDetails(),
                )
            },
            row(R.id.rowBackground, background, R.string.row_background, R.string.row_background_why) {
                openFirst(appDetails())
            },
            row(
                R.id.rowBucket, bucket, R.string.row_bucket,
                if (bucket) R.string.row_bucket_ok else R.string.row_bucket_bad,
            ) { openFirst(appDetails()) },
        )
        findViewById<View>(R.id.rowBackground).visibility = if (modern) View.VISIBLE else View.GONE
        findViewById<View>(R.id.rowBucket).visibility = if (modern) View.VISIBLE else View.GONE
        guided(R.id.rowSleep, R.string.row_sleep, R.string.row_sleep_why, R.string.open) {
            openFirst(
                Intent("com.samsung.android.sm.ACTION_BATTERY"),
                Intent(Settings.ACTION_BATTERY_SAVER_SETTINGS),
                appDetails(),
            )
        }
        guided(R.id.rowRecents, R.string.row_recents, R.string.row_recents_why)
        guided(R.id.rowQuickStart, R.string.row_quickstart, R.string.row_quickstart_why)

        val complete = bad.isEmpty()
        val done = findViewById<View>(R.id.rowDone)
        done.visibility = if (complete) View.VISIBLE else View.GONE
        if (complete) {
            mark(done, Mark.OK, R.string.setup_complete, R.string.setup_complete_why,
                if (setupExpanded) R.string.hide else R.string.show) {
                setupExpanded = !setupExpanded
                render()
            }
        }
        findViewById<View>(R.id.setupList).visibility = if (!complete || setupExpanded) View.VISIBLE else View.GONE
        return bad.firstOrNull()
    }

    /** A detected row; returns the row when it needs fixing. */
    private fun row(id: Int, ok: Boolean, label: Int, why: Int, fix: () -> Unit): View? {
        val v = findViewById<View>(id)
        mark(v, if (ok) Mark.OK else Mark.BAD, label, why, if (ok) null else R.string.fix, fix)
        return if (ok) null else v
    }

    private fun guided(id: Int, label: Int, why: Int, action: Int? = null, onAction: () -> Unit = {}) {
        mark(findViewById(id), Mark.GUIDED, label, why, action, onAction)
    }

    private fun mark(v: View, m: Mark, label: Int, why: Int, action: Int?, onAction: () -> Unit) {
        v.findViewById<ImageView>(R.id.glyph).apply {
            setImageResource(when (m) { Mark.OK -> R.drawable.sq_ok; Mark.BAD -> R.drawable.sq_bad; Mark.GUIDED -> R.drawable.sq_guided })
            contentDescription = getString(when (m) { Mark.OK -> R.string.a11y_ok; Mark.BAD -> R.string.a11y_bad; Mark.GUIDED -> R.string.a11y_guided })
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_YES
        }
        v.findViewById<TextView>(R.id.label).setText(label)
        v.findViewById<TextView>(R.id.why).setText(why)
        v.findViewById<Button>(R.id.action).apply {
            visibility = if (action == null) View.GONE else View.VISIBLE
            if (action != null) setText(action)
            setOnClickListener { onAction() }
        }
    }

    private fun renderTv(c: Config) {
        findViewById<TextView>(R.id.tvName).text = c.host?.let { getString(R.string.tv_name, it) } ?: getString(R.string.tv_no_ip)
        val wifi = HomeNetwork.wifiNetwork(this) != null
        findViewById<Button>(R.id.openTvButton).apply { isEnabled = wifi; alpha = if (wifi) 1f else 0.4f }
        findViewById<TextView>(R.id.openTvHint).apply {
            visibility = if (wifi) View.GONE else View.VISIBLE
            setText(R.string.open_needs_wifi)
        }
    }

    /** A result line led by a square glyph: blue for good, red for a problem, none while in progress. */
    private fun result(v: TextView, ok: Boolean?, text: CharSequence) {
        v.visibility = View.VISIBLE
        v.text = text
        val glyph = when (ok) { true -> R.drawable.sq_ok; false -> R.drawable.sq_bad; null -> 0 }
        v.setCompoundDrawablesRelativeWithIntrinsicBounds(glyph, 0, 0, 0)
    }

    private fun scrollTo(target: View) {
        var y = 0
        var v: View = target
        while (v !== content) {
            y += v.top
            v = v.parent as View
        }
        scroll.smoothScrollTo(0, (y - 20 * resources.displayMetrics.density).toInt().coerceAtLeast(0))
    }

    private fun appDetails() = Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName"))

    /** Opens the first settings screen this phone has (Samsung screens are missing on other phones). */
    private fun openFirst(vararg intents: Intent) {
        for (i in intents) {
            try {
                startActivity(i)
                return
            } catch (e: RuntimeException) {
                // Not on this phone; try the next one.
            }
        }
    }

    private fun refreshLog() {
        val lines = EventLog.read(this).lines().filter { it.isNotBlank() }.takeLast(30)
        logText.text = if (lines.isEmpty()) getString(R.string.log_empty) else lines.joinToString("\n")
    }

    // ---- Actions ---------------------------------------------------------------------------------

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
            pin == null -> { result(tvResult, false, getString(R.string.test_not_paired)); return }
            network == null -> { result(tvResult, false, getString(R.string.test_no_wifi)); return }
            host.isEmpty() -> { result(tvResult, false, getString(R.string.need_ip)); return }
        }
        result(tvResult, null, getString(R.string.testing))
        scope.launch {
            val got = withContext(Dispatchers.IO) { probePin(host, network!!.socketFactory) }
            val ok = got != null && got.equals(pin, ignoreCase = true)
            val msg = when {
                got == null -> getString(R.string.test_no_answer, host)
                ok -> getString(R.string.test_match, host)
                else -> getString(R.string.test_mismatch, host)
            }
            result(tvResult, ok, msg)
            EventLog.add(this@MainActivity, "Test TV: $msg")
        }
    }

    /** Quick action: ask the paired TV to bring V/HOME to the front. */
    private fun openOnTv() {
        val c = Prefs.load(this)
        val host = c.host
        val network = HomeNetwork.wifiNetwork(this)
        if (c.pin == null || host == null || network == null) return
        result(tvResult, null, getString(R.string.open_sending))
        scope.launch {
            val sent = withContext(Dispatchers.IO) {
                runCatching {
                    val client = SsapClient(host, c.clientKey, c.pin, false, network.socketFactory,
                        manifest = Prefs.ssapManifest(this@MainActivity))
                    try {
                        client.open()
                        client.request(LAUNCH_URI, JSONObject().put("id", c.vhomeId), 8_000)
                    } finally {
                        client.close()
                    }
                }
            }
            sent.exceptionOrNull()?.let { EventLog.add(this@MainActivity, "Open V/HOME on TV failed: ${it.message}") }
            result(tvResult, sent.isSuccess, getString(if (sent.isSuccess) R.string.open_sent else R.string.open_failed))
        }
    }

    private fun currentConfig(): Config {
        val saved = Prefs.load(this)
        val ids = homeIdsField.text.toString().split(',').map { it.trim() }.filter { it.isNotEmpty() }
        return saved.copy(
            host = hostField.text.toString().trim().ifEmpty { null } ?: saved.host,
            vhomeId = vhomeField.text.toString().trim().ifEmpty { DEFAULT_VHOME_ID },
            homeIds = ids.ifEmpty { DEFAULT_HOME_IDS },
            doubleHomeEscape = doubleHomeSwitch.isChecked,
        )
    }

    private fun save() {
        Prefs.save(this, currentConfig())
        // Tell a running service to pick up live settings; harmless if it isn't running.
        tell(Notify.ACTION_RELOAD)
    }

    private fun tell(action: String, minutes: Int? = null) {
        val i = Intent(this, WatcherService::class.java).setAction(action)
        if (minutes != null) i.putExtra(WatchStatus.EXTRA_MINUTES, minutes)
        try {
            startService(i)
        } catch (e: RuntimeException) {
            // Service not running; it reads the saved state when it starts.
        }
    }

    private fun pair(field: EditText, out: TextView) {
        val host = field.text.toString().trim()
        if (host.isEmpty()) {
            result(out, false, getString(R.string.need_ip))
            return
        }
        result(out, null, getString(R.string.pair_prompt))
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
                hostField.setText(host)
                result(out, true, getString(R.string.paired_with, host))
                result(tvResult, true, getString(R.string.paired_with, host))
                startWatching()
                tell(WatchStatus.ACTION_RESTART)
                render()
            } catch (e: Exception) {
                EventLog.add(this@MainActivity, "Pair failed: ${e.javaClass.simpleName}: ${e.message}")
                result(out, false, getString(if (e is NotPaired) R.string.pair_not_accepted else R.string.pair_no_answer))
            }
        }
    }

    /** [minutes] 0 = until resumed. The service also stores the time; writing it here keeps the screen right if it isn't running. */
    private fun pause(minutes: Int) {
        Prefs.save(this, Prefs.load(this).copy(paused = true))
        WatchStatus.setPausedUntil(this, if (minutes > 0) System.currentTimeMillis() + minutes * 60_000L else null)
        pauseChoices.visibility = View.GONE
        tell(Notify.ACTION_PAUSE, minutes)
        render()
    }

    private fun resume() {
        Prefs.save(this, Prefs.load(this).copy(paused = false))
        WatchStatus.setPausedUntil(this, null)
        tell(Notify.ACTION_RESUME)
        render()
    }
}
