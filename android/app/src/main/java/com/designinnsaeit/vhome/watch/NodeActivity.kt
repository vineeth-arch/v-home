package com.designinnsaeit.vhome.watch

import android.app.Activity
import android.app.AlertDialog
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.os.Build
import android.os.Bundle
import android.os.SystemClock
import android.text.format.DateFormat
import android.view.View
import android.widget.Button
import android.widget.CheckBox
import android.widget.CompoundButton
import android.widget.EditText
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import java.util.Date
import java.util.concurrent.atomic.AtomicReference
import javax.net.SocketFactory
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import okhttp3.Dns
import org.json.JSONObject

/**
 * The phone side of VNode mode: connect, pair, then watch the node's status and control it. Polls only while
 * on screen; no background work. Wording and button decisions live in [NodeUi].
 */
class NodeActivity : Activity() {
    private enum class Screen { SETUP, FINGERPRINT, CODE, STATUS }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private lateinit var store: NodeStore
    private lateinit var discovery: NodeDiscovery
    private var pollJob: Job? = null
    private var screen = Screen.SETUP
    private var busy = false
    private var resumed = false
    private var enableOnStart = false

    // Pairing in progress (never saved until the owner confirmed the fingerprint and the code worked).
    private var pendingHost: String? = null
    private var pendingNodeId: String? = null

    // What the node last told us. Elapsed times drive staleness; wall times are only for display.
    private var status: NodeStatus? = null
    private var statusAt = 0L
    private var statusWall = 0L
    private var device: DeviceStatus? = null
    private var deviceAt = 0L
    private var deviceWall = 0L
    private var health: NodeHealth? = null
    private var visual: HealthVisual? = null
    private val dash by lazy { HealthDashboard(this) }
    private var healthAt = 0L
    private var healthWall = 0L
    private var healthMissing = false // status works but the node has no (readable) /v1/health
    private var healthOpen = false
    private var problemsSig = ""
    private var allSig = ""
    private var problem: NodeException? = null
    private var rediscoverTried = false
    private var heroStale = false

    private var ledEnabled = true
    private var ledBrightness = 2
    private var ledDirty = false
    private var ledHoldUntil = 0L

    private val found = linkedMapOf<String, NodeCandidate>()
    private val brightnessButtons = mutableListOf<Button>()
    private lateinit var commandButtons: List<View>

    private fun <T : View> v(id: Int): T = findViewById(id)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.installCrashHandler(this)
        setContentView(R.layout.activity_node)
        store = NodeStore(this)
        discovery = NodeDiscovery(this)

        v<EditText>(R.id.nameField).setText(Build.MODEL)
        v<Button>(R.id.connectButton).setOnClickListener { connect(v<EditText>(R.id.hostField).text.toString()) }
        v<Button>(R.id.fpMatch).setOnClickListener { show(Screen.CODE) }
        v<Button>(R.id.fpNoMatch).setOnClickListener {
            pendingHost = null; pendingNodeId = null
            show(Screen.SETUP)
            result(v(R.id.setupResult), false, getString(R.string.node_fp_warning))
        }
        v<Button>(R.id.pairButton).setOnClickListener { pair() }
        v<Button>(R.id.healthToggle).setOnClickListener { healthOpen = !healthOpen; renderHealth() }
        v<View>(R.id.healthBanner).setOnClickListener { scrollToProblems() }
        v<Button>(R.id.usePhoneFromSetup).setOnClickListener { switchToStandalone() }

        v<Button>(R.id.launchButton).setOnClickListener {
            command(v(R.id.actionResult), NodeUi::launchText) { it.command("/v1/tv/launch") }
        }
        v<Button>(R.id.pauseButton).setOnClickListener {
            command(v(R.id.actionResult)) { it.command("/v1/pause", JSONObject().put("minutes", 60)) }
        }
        v<Button>(R.id.resumeButton).setOnClickListener { command(v(R.id.actionResult)) { it.command("/v1/resume") } }
        v<Button>(R.id.turnOnButton).setOnClickListener { enableNode {} }

        v<Button>(R.id.tvPairToggle).setOnClickListener { toggleTvPair() }
        v<Button>(R.id.tvPairButton).setOnClickListener { pairTv() }

        buildBrightness()
        v<CompoundButton>(R.id.ledSwitch).setOnCheckedChangeListener { _, on ->
            if (on != ledEnabled) { ledEnabled = on; ledDirty = true }
        }
        v<Button>(R.id.ledApply).setOnClickListener { applyLeds() }
        v<Button>(R.id.restartServiceButton).setOnClickListener {
            command(v(R.id.piResult)) { it.command("/v1/device/restart-service") }
        }
        v<Button>(R.id.rebootButton).setOnClickListener {
            confirm(R.string.node_dialog_reboot_title, R.string.node_dialog_reboot_body, R.string.node_yes_reboot) {
                command(v(R.id.piResult)) { it.command("/v1/device/reboot", JSONObject().put("confirm", "reboot")) }
            }
        }
        v<Button>(R.id.shutdownButton).setOnClickListener {
            confirm(R.string.node_dialog_shutdown_title, R.string.node_dialog_shutdown_body, R.string.node_yes_shutdown) {
                command(v(R.id.piResult)) { it.command("/v1/device/shutdown", JSONObject().put("confirm", "shutdown")) }
            }
        }

        v<Button>(R.id.diagButton).setOnClickListener { runDiagnostics() }
        v<Button>(R.id.diagCopy).setOnClickListener {
            getSystemService(ClipboardManager::class.java)
                .setPrimaryClip(ClipData.newPlainText("V/HOME node diagnostics", v<TextView>(R.id.diagText).text))
            Toast.makeText(this, R.string.node_copied, Toast.LENGTH_SHORT).show()
        }
        v<Button>(R.id.usePhoneButton).setOnClickListener { usePhoneInstead() }
        v<Button>(R.id.forgetButton).setOnClickListener {
            confirm(R.string.node_dialog_forget_title, R.string.node_dialog_forget_body, R.string.node_yes_forget) { forgetNode() }
        }

        commandButtons = listOf(
            R.id.connectButton, R.id.fpMatch, R.id.fpNoMatch, R.id.pairButton, R.id.launchButton, R.id.pauseButton,
            R.id.resumeButton, R.id.turnOnButton, R.id.tvPairButton, R.id.ledApply, R.id.restartServiceButton,
            R.id.rebootButton, R.id.shutdownButton, R.id.diagButton, R.id.usePhoneButton, R.id.forgetButton,
        ).map { v<View>(it) } + brightnessButtons

        // Coming back from standalone mode: the phone keeps watching until the node confirms it does.
        enableOnStart = intent.getBooleanExtra(EXTRA_ENABLE, false) && store.isPaired()
        show(if (store.isPaired()) Screen.STATUS else Screen.SETUP)
        if (screen == Screen.SETUP && Prefs.mode(this) == ControllerMode.VNODE) notice(getString(R.string.node_phone_off))
    }

    override fun onResume() {
        super.onResume()
        resumed = true
        when (screen) {
            Screen.SETUP -> startDiscovery()
            Screen.STATUS -> { startPolling(); scheduleHealthJob() }
            else -> {}
        }
        if (enableOnStart && screen == Screen.STATUS) {
            enableOnStart = false
            enableNode {
                Prefs.setMode(this, ControllerMode.VNODE)
                stopWatcherService()
                scheduleHealthJob()
            }
        }
    }

    override fun onPause() {
        resumed = false
        pollJob?.cancel(); pollJob = null
        discovery.stop()
        notice(null)
        super.onPause()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    @Suppress("DEPRECATION", "OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        if (screen == Screen.FINGERPRINT || screen == Screen.CODE) { show(Screen.SETUP); return }
        super.onBackPressed()
    }

    // ---- Screens ---------------------------------------------------------------------------------

    private fun show(s: Screen) {
        screen = s
        fun vis(id: Int, on: Boolean) { v<View>(id).visibility = if (on) View.VISIBLE else View.GONE }
        vis(R.id.setupSection, s == Screen.SETUP)
        vis(R.id.fpSection, s == Screen.FINGERPRINT)
        vis(R.id.codeSection, s == Screen.CODE)
        vis(R.id.statusSection, s == Screen.STATUS)
        if (s != Screen.SETUP) discovery.stop()
        if (s == Screen.SETUP) {
            vis(R.id.usePhoneFromSetup, Prefs.mode(this) == ControllerMode.VNODE)
            if (hasWindowFocus()) startDiscovery()
        }
        if (s == Screen.STATUS) { renderStatus(); startPolling() } else { pollJob?.cancel(); pollJob = null }
        v<View>(R.id.scroll).scrollTo(0, 0)
        applyEnabled()
    }

    private fun notice(text: String?) {
        v<TextView>(R.id.notice).apply {
            visibility = if (text == null) View.GONE else View.VISIBLE
            if (text != null) this.text = text
        }
    }

    // ---- Setup: find, connect, check the fingerprint, pair --------------------------------------

    private fun startDiscovery() {
        found.clear()
        renderFound()
        discovery.start { c ->
            found[c.host] = c
            renderFound()
        }
    }

    private fun renderFound() {
        val list = v<LinearLayout>(R.id.nodeList)
        list.removeAllViews()
        found.values.forEach { c ->
            val row = layoutInflater.inflate(R.layout.node_found, list, false)
            row.findViewById<TextView>(R.id.foundName).text = c.name
            row.findViewById<TextView>(R.id.foundHost).text = c.host
            row.setOnClickListener {
                v<EditText>(R.id.hostField).setText(c.host)
                connect(c.host)
            }
            list.addView(row)
        }
        v<TextView>(R.id.nodeListHint).setText(if (found.isEmpty()) R.string.node_looking else R.string.node_found_label)
        v<View>(R.id.nodeListHint).visibility = if (found.isEmpty()) View.VISIBLE else View.GONE
    }

    /** First contact trusts the certificate once, only to learn its hash; the owner then compares it by eye. */
    private fun connect(rawHost: String) {
        val host = NodeClient.normalizeHost(rawHost)
        if (host.isEmpty() || busy) return
        setBusy(true)
        result(v(R.id.setupResult), null, getString(R.string.node_connecting))
        scope.launch {
            try {
                val seen = AtomicReference<String?>()
                val info = NodeClient(host, null, true, socketFactory(), null, { seen.set(it) }, dns = dns()).info()
                val id = info.nodeId.lowercase()
                if (seen.get() != id) throw NodeException(NodeProblem.DIFFERENT_DEVICE, "node id does not match its certificate")
                pendingHost = host; pendingNodeId = id
                v<TextView>(R.id.fpText).text = NodeRules.fingerprintGroups(id)
                v<TextView>(R.id.setupResult).visibility = View.GONE
                show(Screen.FINGERPRINT)
            } catch (e: NodeException) {
                result(v(R.id.setupResult), false, NodeUi.problemMessage(e.problem, vpnActive()))
            } finally {
                setBusy(false)
            }
        }
    }

    private fun pair() {
        val host = pendingHost
        val id = pendingNodeId
        val raw = v<EditText>(R.id.codeField).text.toString()
        if (host == null || id == null || busy) return
        if (!NodeUi.codeLooksComplete(raw)) {
            result(v(R.id.codeResult), false, NodeUi.problemMessage(NodeProblem.INVALID))
            return
        }
        val name = v<EditText>(R.id.nameField).text.toString().trim().ifEmpty { Build.MODEL }
        setBusy(true)
        result(v(R.id.codeResult), null, getString(R.string.node_pairing))
        scope.launch {
            var paired = false
            try {
                // From here on the connection is pinned to what the owner confirmed.
                val (phoneId, token) = NodeClient(host, id, false, socketFactory(), null, dns = dns())
                    .pair(NodeUi.normalizeCode(raw), name)
                store.save(host, id, phoneId, name, token)
                Prefs.setMode(this@NodeActivity, ControllerMode.VNODE)
                stopWatcherService()
                v<EditText>(R.id.codeField).setText("")
                pendingHost = null; pendingNodeId = null
                status = null; device = null; health = null; visual = null; healthMissing = false; problem = null
                scheduleHealthJob()
                notice(getString(R.string.node_paired_ok))
                show(Screen.STATUS)
                paired = true
            } catch (e: NodeException) {
                result(v(R.id.codeResult), false, NodeUi.problemMessage(e.problem, vpnActive(), pairing = true))
            } finally {
                setBusy(false)
            }
            // The owner chose the node; a node that had been handed back to the phone must watch again.
            if (paired) enableNode {}
        }
    }

    // ---- Status polling --------------------------------------------------------------------------

    private fun startPolling() {
        if (!resumed || pollJob?.isActive == true) return
        pollJob = scope.launch {
            var tick = 0
            while (isActive) {
                if (tick % 5 == 0) refresh()
                ageTick(); tick++
                delay(1000)
            }
        }
    }

    private suspend fun refresh() {
        try {
            val c = client()
            val s = c.status()
            statusAt = SystemClock.elapsedRealtime(); statusWall = System.currentTimeMillis()
            status = s; problem = null; rediscoverTried = false
            NodeHealthJob.rememberWifi(this)
            try {
                val hj = c.healthJson(); health = NodeHealth.parse(hj); visual = NodeHealthVisual.parse(hj); healthAt = SystemClock.elapsedRealtime(); healthWall = System.currentTimeMillis()
                healthMissing = false
            } catch (e: NodeException) {
                // Keep what we have: it goes stale and is greyed. No health at all = an older node.
                healthMissing = health == null
            }
            try {
                device = c.device(); deviceAt = SystemClock.elapsedRealtime(); deviceWall = System.currentTimeMillis()
            } catch (e: NodeException) {
                // The device card just ages; the status above is still good.
            }
        } catch (e: NodeException) {
            problem = e
            if (e.problem == NodeProblem.NO_ANSWER && !rediscoverTried) { rediscoverTried = true; rediscover() }
        }
        renderStatus()
    }

    /** The node's address may have changed (DHCP). Accept a new address only if the pinned certificate answers there. */
    private suspend fun rediscover() {
        val id = store.nodeId ?: return
        val sf = runCatching { socketFactory() }.getOrNull() ?: return
        for (c in discovery.scan()) {
            if (c.host == store.host) continue
            if (c.idPrefix != null && !id.startsWith(c.idPrefix.lowercase())) continue
            try {
                if (NodeClient(c.host, id, false, sf, null, dns = dns()).info().nodeId.equals(id, ignoreCase = true)) {
                    store.updateHost(c.host)
                    EventLog.add(this, "node moved to ${c.host}")
                    problem = null
                    return
                }
            } catch (e: NodeException) {
                if (e.problem == NodeProblem.DIFFERENT_DEVICE && c.idPrefix != null) problem = e
            }
        }
    }

    /** Once a second: only the age labels, and a full redraw if the data just went stale. */
    private fun ageTick() {
        renderHealth()
        val s = status ?: return
        val now = SystemClock.elapsedRealtime()
        v<TextView>(R.id.updatedText).setIfChanged(NodeUi.updatedLabel(now - statusAt))
        if (NodeUi.isStale(s.headline, statusAt, now, s.tvAgeS) != heroStale || deviceStale(now) != piStaleShown) renderStatus()
    }

    private var piStaleShown = false
    private fun deviceStale(now: Long) = device != null && NodeRules.isStale(deviceAt, now, 0.0)

    private fun lastSeen(wall: Long, ageS: Double?): String =
        DateFormat.getTimeFormat(this).format(Date(wall - ((ageS ?: 0.0) * 1000).toLong()))

    private fun renderStatus() {
        if (screen != Screen.STATUS) return
        val s = status
        val now = SystemClock.elapsedRealtime()
        val p = problem
        val vpn = vpnActive()
        fun vis(id: Int, on: Boolean) { v<View>(id).visibility = if (on) View.VISIBLE else View.GONE }

        // Hero
        val hero: NodeUi.Hero
        if (s != null) {
            heroStale = NodeUi.isStale(s.headline, statusAt, now, s.tvAgeS)
            hero = NodeUi.hero(s, heroStale, lastSeen(statusWall, s.tvAgeS))
        } else {
            heroStale = false
            hero = if (p != null) NodeUi.Hero(NodeUi.problemTitle(p.problem), NodeUi.problemMessage(p.problem, vpn), NodeUi.problemTone(p.problem))
            else NodeUi.Hero(getString(R.string.node_connecting), "", NodeUi.Tone.QUIET)
        }
        val (bg, fg) = when (hero.tone) {
            NodeUi.Tone.GOOD -> R.color.blue to R.color.on_blue
            NodeUi.Tone.QUIET -> R.color.grey to R.color.ink
            NodeUi.Tone.BAD -> R.color.red to R.color.on_colour
            NodeUi.Tone.WAIT -> R.color.yellow to R.color.on_colour
        }
        v<View>(R.id.heroBlock).setBackgroundColor(getColor(bg))
        v<TextView>(R.id.heroTitle).apply { setIfChanged(hero.title); setTextColor(getColor(fg)) }
        v<TextView>(R.id.heroDetail).apply {
            setIfChanged(if (s != null && p != null) NodeUi.problemMessage(p.problem, vpn) else "")
            setTextColor(getColor(fg))
        }
        v<TextView>(R.id.heroExplain).apply { setIfChanged(hero.explain); setTextColor(getColor(fg)) }
        v<TextView>(R.id.updatedText).apply { setIfChanged(if (s != null) NodeUi.updatedLabel(now - statusAt) else ""); setTextColor(getColor(fg)) }

        // Actions and cards need data from the node.
        val resume = s != null && NodeUi.showResume(s.watcherState, s.paused)
        val turnOn = s != null && NodeUi.showTurnOn(s.watcherState)
        vis(R.id.launchButton, s != null)
        vis(R.id.resumeButton, resume)
        vis(R.id.turnOnButton, turnOn)
        vis(R.id.pauseButton, s != null && !resume && !turnOn)
        vis(R.id.cardTvSection, s != null)
        vis(R.id.cardWatcherSection, s != null)
        if (s != null) {
            val tvStale = heroStale
            val seen = lastSeen(statusWall, s.tvAgeS)
            setRows(v(R.id.cardTv), listOfNotNull(
                "State" to NodeUi.tvStateLabel(s.tvState, tvStale, seen),
                s.tvHost?.let { "Address" to it },
                s.tvPower?.let { "Power" to it },
                s.tvForeground?.let { "In front" to it },
                s.tvLastError?.let { "Last error" to it },
            ))
            val until = NodeUi.parseInstantMs(s.pausedUntil)
            setRows(v(R.id.cardWatcher), listOfNotNull(
                "State" to NodeUi.watcherStateLabel(s.watcherState),
                if (s.paused) "Paused until" to (until?.let { DateFormat.getTimeFormat(this).format(Date(it)) } ?: "You resume it") else null,
                "Redirects" to s.redirects.toString(),
                "Last speed" to NodeUi.latencyText(s.lastLatencyS),
                s.lastFailure?.let { "Last failure" to it },
            ))
            vis(R.id.repinCheck, NodeUi.showRepin(s.tvState))
            if (!NodeUi.showRepin(s.tvState)) v<CheckBox>(R.id.repinCheck).isChecked = false
            NodeUi.pairingText(s.pairingState, s.pairingDetail)?.let {
                result(v(R.id.tvPairResult), s.pairingState == "done", it)
            }
        }
        renderHealth()
        renderDevice(now)
        applyEnabled()
    }

    // ---- Health ----------------------------------------------------------------------------------

    private fun healthStale(now: Long): Boolean =
        problem != null || health?.let { NodeRules.isStale(healthAt, now, it.ageS) } != false

    /** Updates rows in place (no rebuild) unless the list of indicators changed, so TalkBack focus survives the polling. */
    private fun renderHealth() {
        if (screen != Screen.STATUS) return
        val now = SystemClock.elapsedRealtime()
        val h = health
        val p = problem
        val section = v<View>(R.id.healthSection)
        val summary = v<TextView>(R.id.healthSummary)
        if (h == null && p == null && !healthMissing) { section.visibility = View.GONE; return }
        section.visibility = View.VISIBLE
        if (h == null && p == null) {
            summary.setIfChanged(getString(R.string.node_health_unavailable))
            summary.setCompoundDrawablesRelativeWithIntrinsicBounds(R.drawable.sq_info, 0, 0, 0)
            summary.setTextColor(getColor(R.color.ink))
            summary.visibility = View.VISIBLE
            v<View>(R.id.healthDash).visibility = View.GONE
            v<View>(R.id.healthToggle).visibility = View.GONE
            v<View>(R.id.healthAll).visibility = View.GONE
            return
        }
        v<View>(R.id.healthProblems).visibility = View.VISIBLE
        v<View>(R.id.healthToggle).visibility = View.VISIBLE
        v<View>(R.id.healthDash).visibility = View.VISIBLE
        summary.visibility = View.GONE
        val stale = healthStale(now)
        val seen = lastSeen(if (h != null) healthWall else statusWall, h?.ageS)
        val local = NodeHealthUi.connection(p?.problem, stale, now - healthAt, vpnActive(), seen)
        val view = NodeHealthUi.build(local, h, stale)

        dash.render(h?.items.orEmpty(), visual, stale, view, if (stale) local.detail else null)

        val problemsBox = v<LinearLayout>(R.id.healthProblems)
        problemsBox.visibility = if (view.problems.isEmpty()) View.GONE else View.VISIBLE
        val psig = view.problems.joinToString("|") { "${it.group}/${it.key}" }
        if (psig != problemsSig) {
            problemsSig = psig
            problemsBox.removeAllViews()
            view.problems.forEach { problemsBox.addView(layoutInflater.inflate(R.layout.node_health_row, problemsBox, false)) }
        }
        view.problems.forEachIndexed { i, it -> bindHealthRow(problemsBox.getChildAt(i), it, stale, seen, true) }

        // Status lights: everything without a gauge, minus what the problem list already shows.
        val shownAsProblem = view.problems.map { NodeHealthVisual.id(it) }.toSet()
        val groups = NodeHealthVisual.lights(view.groups, visual, NodeHealthVisual.throttleIds(h?.items.orEmpty(), visual)).map { (g, items) -> g to items.filter { NodeHealthVisual.id(it) !in shownAsProblem } }
            .filter { it.second.isNotEmpty() }
        val count = groups.sumOf { it.second.size }
        val allBox = v<LinearLayout>(R.id.healthAll)
        val asig = groups.joinToString("|") { (g, items) -> g + ":" + items.joinToString(",") { it.key } }
        if (asig != allSig) {
            allSig = asig
            allBox.removeAllViews()
            groups.forEachIndexed { gi, (g, items) ->
                allBox.addView(TextView(this, null, 0, R.style.T_Small_Header).apply {
                    text = NodeHealthUi.groupTitle(g)
                    isAllCaps = false
                    setPadding(0, if (gi == 0) 0 else (20 * resources.displayMetrics.density).toInt(), 0, 0)
                    if (Build.VERSION.SDK_INT >= 28) isAccessibilityHeading = true
                })
                items.forEach { allBox.addView(layoutInflater.inflate(R.layout.node_health_row, allBox, false)) }
            }
        }
        var idx = 0
        groups.forEach { (_, items) ->
            idx++ // group header
            items.forEach { bindHealthRow(allBox.getChildAt(idx++), it, stale, seen, false) }
        }
        allBox.visibility = if (healthOpen && count > 0) View.VISIBLE else View.GONE
        v<Button>(R.id.healthToggle).apply {
            visibility = if (count > 0) View.VISIBLE else View.GONE
            setIfChanged(NodeHealthUi.lightsToggleText(count, healthOpen))
        }
    }

    /** Banner tap: bring the first problem into view. */
    private fun scrollToProblems() {
        val box = v<View>(R.id.healthProblems)
        if (box.visibility != View.VISIBLE) return
        val sv = v<android.widget.ScrollView>(R.id.scroll)
        val r = android.graphics.Rect(0, 0, box.width, box.height)
        sv.offsetDescendantRectToMyCoords(box, r)
        sv.smoothScrollTo(0, maxOf(0, r.top - (24 * resources.displayMetrics.density).toInt()))
    }

    private fun bindHealthRow(row: View, item: HealthItem, stale: Boolean, seen: String, showDetail: Boolean) {
        val itemStale = stale && item.group != NodeHealthUi.PHONE
        row.findViewById<ImageView>(R.id.hMark).setImageResource(markRes(item.level, itemStale))
        row.findViewById<TextView>(R.id.hLabel).setIfChanged(item.label)
        row.findViewById<TextView>(R.id.hValue).apply {
            setIfChanged(NodeHealthUi.valueText(item, stale, seen))
            setTextColor(getColor(colourRes(NodeHealthUi.colour(item.level, itemStale))))
        }
        row.findViewById<TextView>(R.id.hDetail).apply {
            val on = showDetail && !itemStale && item.detail.isNotBlank()
            visibility = if (on) View.VISIBLE else View.GONE
            if (on) {
                setIfChanged(item.detail)
                setTextColor(getColor(colourRes(NodeHealthUi.colour(item.level, false))))
            }
        }
        row.contentDescription = NodeHealthUi.rowDescription(item, stale, seen)
    }

    private fun colourRes(c: NodeHealthUi.Colour): Int = when (c) {
        NodeHealthUi.Colour.NORMAL -> R.color.ink
        NodeHealthUi.Colour.RED -> R.color.red
        NodeHealthUi.Colour.AMBER -> R.color.warn_text
        NodeHealthUi.Colour.GREY -> R.color.text_dim
    }

    private fun markRes(level: HealthLevel, stale: Boolean): Int = when {
        stale -> R.drawable.sq_info
        level == HealthLevel.ERROR -> R.drawable.sq_bad
        level == HealthLevel.WARN -> R.drawable.sq_guided
        level == HealthLevel.OK -> R.drawable.sq_ok
        else -> R.drawable.sq_info
    }

    private fun scheduleHealthJob() {
        if (Prefs.mode(this) == ControllerMode.VNODE && store.isPaired()) NodeHealthJob.schedule(this)
    }

    private fun renderDevice(now: Long) {
        val d = device
        v<View>(R.id.cardPiSection).visibility = if (d != null && status != null) View.VISIBLE else View.GONE
        if (d == null) return
        piStaleShown = deviceStale(now)
        // The health list covers every reading below; they only remain for a node that has no /v1/health.
        val readings = health == null
        v<TextView>(R.id.piStale).apply {
            visibility = if (piStaleShown && readings) View.VISIBLE else View.GONE
            text = "Last seen ${DateFormat.getTimeFormat(this@NodeActivity).format(Date(deviceWall))}. These numbers may be out of date."
        }
        setRows(v(R.id.cardPi), if (!readings) listOfNotNull(
            if (d.ledsAvailable && d.ledsThermalOff) "LEDs" to "Off while the Pi is hot" else null,
        ) else listOfNotNull(
            "Temperature" to (d.tempC?.let { String.format("%.1f °C", it) } ?: "Unknown"),
            "Throttling" to NodeUi.throttledText(d.throttled),
            "Memory" to "${NodeUi.mbText(d.memUsedMb)} of ${NodeUi.mbText(d.memTotalMb)}",
            "Disk free" to NodeUi.mbText(d.diskFreeMb),
            "Uptime" to NodeUi.durationText(d.uptimeS),
            "Wi-Fi" to NodeUi.wifiText(d.wifiBars, d.wifiDbm),
            if (d.ledsAvailable && d.ledsThermalOff) "LEDs" to "Off while the Pi is hot" else null,
        ))
        v<View>(R.id.ledGroup).visibility = if (d.ledsAvailable) View.VISIBLE else View.GONE
        if (d.ledsAvailable && !ledDirty && now >= ledHoldUntil) {
            ledEnabled = d.ledsEnabled; ledBrightness = d.ledsBrightness.coerceIn(1, 4)
        }
        v<CompoundButton>(R.id.ledSwitch).isChecked = ledEnabled
        renderBrightness()
    }

    private fun setRows(c: LinearLayout, rows: List<Pair<String, String>>) {
        while (c.childCount > rows.size) c.removeViewAt(c.childCount - 1)
        rows.forEachIndexed { i, (label, value) ->
            val row = if (i < c.childCount) c.getChildAt(i)
            else layoutInflater.inflate(R.layout.node_kv, c, false).also { c.addView(it) }
            row.findViewById<TextView>(R.id.kvLabel).setIfChanged(label)
            row.findViewById<TextView>(R.id.kvValue).setIfChanged(value)
        }
    }

    // ---- Commands --------------------------------------------------------------------------------

    /** Sends one command, shows the outcome, then refreshes the status. Never retries; buttons stay off meanwhile. */
    private fun command(
        out: TextView, text: (CommandResult) -> String = NodeUi::commandText, onConfirmed: () -> Unit = {},
        call: suspend (NodeClient) -> CommandResult,
    ) {
        if (busy) return
        setBusy(true)
        result(out, null, "Sending…")
        scope.launch {
            try {
                val r = call(client())
                if (r.outcome == Outcome.CONFIRMED) onConfirmed()
                result(out, when (r.outcome) { Outcome.CONFIRMED -> true; Outcome.FAILED -> false; else -> null }, text(r))
            } catch (e: NodeException) {
                result(out, if (e.problem == NodeProblem.NO_ANSWER) null else false, NodeUi.commandFailure(e, vpnActive()))
            }
            refresh()
            setBusy(false)
        }
    }

    private fun enableNode(onConfirmed: () -> Unit) =
        command(v(R.id.actionResult), onConfirmed = onConfirmed) { it.command("/v1/watcher", JSONObject().put("enabled", true)) }

    private fun applyLeds() {
        command(v(R.id.piResult)) {
            it.command("/v1/device/leds", JSONObject().put("enabled", ledEnabled).put("brightness", ledBrightness))
                .also { r ->
                    if (r.outcome == Outcome.ACCEPTED || r.outcome == Outcome.CONFIRMED) {
                        ledDirty = false
                        ledHoldUntil = SystemClock.elapsedRealtime() + 15_000 // the node applies it within 10 s
                    }
                }
        }
    }

    private fun buildBrightness() {
        val row = v<LinearLayout>(R.id.brightnessRow)
        val dp = resources.displayMetrics.density
        for (i in 1..4) {
            val b = Button(this, null, 0, R.style.Btn_Ghost).apply {
                text = i.toString()
                contentDescription = getString(R.string.node_a11y_brightness, i)
                setPadding(0, 0, 0, 0)
                layoutParams = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f)
                    .apply { if (i > 1) marginStart = (8 * dp).toInt() }
                setOnClickListener { ledBrightness = i; ledDirty = true; renderBrightness() }
            }
            brightnessButtons += b
            row.addView(b)
        }
    }

    private fun renderBrightness() {
        brightnessButtons.forEachIndexed { idx, b ->
            val on = idx + 1 == ledBrightness
            b.isSelected = on
            b.setBackgroundResource(if (on) R.drawable.node_btn_primary else R.drawable.btn_ghost)
            b.setTextColor(getColor(if (on) R.color.on_blue else R.color.ink))
            b.setTypeface(null, if (on) android.graphics.Typeface.BOLD else android.graphics.Typeface.NORMAL)
        }
    }

    private fun toggleTvPair() {
        val body = v<View>(R.id.tvPairBody)
        val open = body.visibility != View.VISIBLE
        body.visibility = if (open) View.VISIBLE else View.GONE
        val field = v<EditText>(R.id.tvHostField)
        if (open && field.text.isNullOrBlank()) {
            scope.launch {
                try {
                    val tvs = client().tvDiscover()
                    (tvs.firstOrNull { it.pinned } ?: tvs.firstOrNull())?.let { if (field.text.isNullOrBlank()) field.setText(it.host) }
                } catch (e: NodeException) {
                    // Typing the address still works.
                }
            }
        }
    }

    private fun pairTv() {
        val host = v<EditText>(R.id.tvHostField).text.toString().trim()
        val out = v<TextView>(R.id.tvPairResult)
        if (host.isEmpty()) { result(out, false, getString(R.string.need_ip)); return }
        val repin = v<CheckBox>(R.id.repinCheck).let { it.visibility == View.VISIBLE && it.isChecked }
        command(out, { r ->
            if (r.outcome == Outcome.ACCEPTED) getString(R.string.pair_prompt) else NodeUi.commandText(r)
        }) { it.command("/v1/tv/pair", JSONObject().put("host", host).put("repin", repin)) }
    }

    // ---- Diagnostics and phones ------------------------------------------------------------------

    private fun localFacts(): String {
        val wifi = HomeNetwork.wifiNetwork(this) != null
        return "Phone: on Wi-Fi ${if (wifi) "yes" else "no"}, VPN active ${if (vpnActive()) "yes" else "no"}\n" +
            "Node: ${store.host ?: "none"}, id ${store.nodeId?.take(24) ?: "none"}\n" +
            "Last error: ${problem?.problem?.name ?: "none"}" + problem?.message?.let { " ($it)" }.orEmpty()
    }

    private fun runDiagnostics() {
        if (busy) return
        setBusy(true)
        val text = v<TextView>(R.id.diagText)
        v<View>(R.id.diagScroll).visibility = View.VISIBLE
        v<View>(R.id.diagCopy).visibility = View.VISIBLE
        text.text = localFacts() + "\n\nAsking the node…"
        scope.launch {
            try {
                val c = client()
                val d = c.diagnostics()
                text.text = localFacts() + "\n\n" + d
                renderPhones(c.phones())
            } catch (e: NodeException) {
                text.text = localFacts() + "\n\n" + NodeUi.problemMessage(e.problem, vpnActive())
            } finally {
                setBusy(false)
            }
        }
    }

    private fun renderPhones(phones: List<NodePhone>) {
        val list = v<LinearLayout>(R.id.phonesList)
        list.removeAllViews()
        v<View>(R.id.phonesLabel).visibility = if (phones.isEmpty()) View.GONE else View.VISIBLE
        phones.forEach { ph ->
            val row = layoutInflater.inflate(R.layout.node_phone, list, false)
            val mine = ph.isThis || ph.id == store.phoneId
            row.findViewById<TextView>(R.id.phoneName).text = if (mine) "${ph.name} (this phone)" else ph.name
            row.findViewById<Button>(R.id.phoneRevoke).apply {
                contentDescription = getString(R.string.node_revoke) + " " + ph.name
                setOnClickListener {
                    confirm(
                        R.string.node_dialog_revoke_title,
                        if (mine) R.string.node_dialog_revoke_this_body else R.string.node_dialog_revoke_body,
                        R.string.node_yes_revoke,
                    ) { revoke(ph, mine) }
                }
            }
            list.addView(row)
        }
    }

    private fun revoke(ph: NodePhone, mine: Boolean) {
        if (busy) return
        setBusy(true)
        val out = v<TextView>(R.id.phonesResult)
        scope.launch {
            try {
                val c = client()
                val r = c.revoke(ph.id)
                result(out, r.outcome == Outcome.CONFIRMED, NodeUi.commandText(r))
                if (r.outcome == Outcome.CONFIRMED) {
                    if (mine) forgetNode() else renderPhones(c.phones())
                }
            } catch (e: NodeException) {
                result(out, false, NodeUi.commandFailure(e, vpnActive()))
            } finally {
                setBusy(false)
            }
        }
    }

    // ---- Controller ------------------------------------------------------------------------------

    private fun usePhoneInstead() {
        if (busy) return
        setBusy(true)
        val out = v<TextView>(R.id.controllerResult)
        result(out, null, "Asking the node to stop watching…")
        scope.launch {
            var why: String? = null
            val confirmed = try {
                client().command("/v1/watcher", JSONObject().put("enabled", false)).outcome == Outcome.CONFIRMED
            } catch (e: NodeException) {
                why = NodeUi.commandFailure(e, vpnActive())
                false
            }
            setBusy(false)
            if (NodeRules.canSwitchToStandalone(confirmed, false)) switchToStandalone()
            else {
                out.visibility = View.GONE
                askSwitchAnyway(why)
            }
        }
    }

    /** Never switches by itself: the owner must say the node is unplugged or disconnected. */
    private fun askSwitchAnyway(why: String?) {
        val pad = (24 * resources.displayMetrics.density).toInt()
        val check = CheckBox(this).apply {
            setText(R.string.node_dialog_unplugged); minHeight = (48 * resources.displayMetrics.density).toInt()
        }
        val body = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(pad, pad / 2, pad, 0)
            addView(TextView(context).apply {
                text = getString(R.string.node_dialog_switch_body) + why?.let { "\n\n$it" }.orEmpty()
                textSize = 16f
            })
            addView(check)
        }
        val dialog = AlertDialog.Builder(this)
            .setTitle(R.string.node_dialog_switch_title)
            .setView(body)
            .setNegativeButton(R.string.node_cancel, null)
            .setPositiveButton(R.string.node_switch_anyway) { _, _ ->
                if (NodeRules.canSwitchToStandalone(false, check.isChecked)) switchToStandalone()
            }.show()
        val go = dialog.getButton(AlertDialog.BUTTON_POSITIVE)
        go.isEnabled = false
        check.setOnCheckedChangeListener { _, on -> go.isEnabled = NodeRules.canSwitchToStandalone(false, on) }
    }

    private fun switchToStandalone() {
        Prefs.setMode(this, ControllerMode.STANDALONE)
        NodeHealthJob.cancel(this)
        if (Prefs.load(this).pin != null) {
            runCatching { startForegroundService(Intent(this, WatcherService::class.java)) }
                .onFailure { EventLog.add(this, "could not start watcher: ${it.javaClass.simpleName}: ${it.message}") }
        }
        startActivity(Intent(this, MainActivity::class.java))
        finish()
    }

    private fun forgetNode() {
        store.forget()
        NodeHealthJob.cancel(this)
        status = null; device = null; health = null; visual = null; healthMissing = false; problem = null
        pendingHost = null; pendingNodeId = null
        v<View>(R.id.diagScroll).visibility = View.GONE
        v<View>(R.id.diagCopy).visibility = View.GONE
        notice(getString(R.string.node_forgot))
        show(Screen.SETUP)
    }

    private fun stopWatcherService() {
        runCatching { stopService(Intent(this, WatcherService::class.java)) }
    }

    // ---- Plumbing --------------------------------------------------------------------------------

    private fun socketFactory(): SocketFactory =
        HomeNetwork.wifiNetwork(this)?.socketFactory ?: throw NodeException(NodeProblem.NOT_ON_WIFI, "no Wi-Fi")

    private fun dns(): Dns {
        val net = HomeNetwork.wifiNetwork(this) ?: return Dns.SYSTEM
        return object : Dns {
            override fun lookup(hostname: String): List<java.net.InetAddress> =
                runCatching { net.getAllByName(hostname).toList() }.getOrElse { Dns.SYSTEM.lookup(hostname) }
        }
    }

    private fun client(): NodeClient {
        val host = store.host
        val id = store.nodeId
        val token = store.token()
        if (host == null || id == null || token == null) throw NodeException(NodeProblem.UNAUTHORIZED, "not paired")
        return NodeClient(host, id, false, socketFactory(), token, dns = dns())
    }

    private fun vpnActive(): Boolean {
        val cm = getSystemService(ConnectivityManager::class.java)
        val caps = cm.getNetworkCapabilities(cm.activeNetwork ?: return false)
        return caps?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
    }

    private fun setBusy(b: Boolean) { busy = b; applyEnabled() }

    private fun applyEnabled() {
        if (!::commandButtons.isInitialized) return
        commandButtons.forEach { it.isEnabled = !busy; it.alpha = if (busy) 0.4f else 1f }
    }

    private fun TextView.setIfChanged(t: CharSequence) { if (text.toString() != t.toString()) text = t }

    /** A result line led by a square glyph: blue for good, red for a problem, none while in progress. */
    private fun result(v: TextView, ok: Boolean?, text: CharSequence) {
        v.visibility = View.VISIBLE
        v.text = text
        val glyph = when (ok) { true -> R.drawable.sq_ok; false -> R.drawable.sq_bad; null -> 0 }
        v.setCompoundDrawablesRelativeWithIntrinsicBounds(glyph, 0, 0, 0)
    }

    private fun confirm(title: Int, message: Int, yes: Int, action: () -> Unit) {
        AlertDialog.Builder(this).setTitle(title).setMessage(message)
            .setNegativeButton(R.string.node_cancel, null)
            .setPositiveButton(yes) { _, _ -> action() }.show()
    }

    companion object {
        /** MainActivity sets this when a node is already paired: switch back to the node and ask it to watch. */
        const val EXTRA_ENABLE = "enable_node"
    }
}
