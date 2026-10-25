package com.designinnsaeit.vhome.watch

import android.app.Activity
import android.graphics.drawable.GradientDrawable
import android.view.View
import android.view.ViewGroup
import android.widget.LinearLayout
import android.widget.TextView

/** Pure rules for the Health section and the problem alerts. The node decides every level; this only arranges and words them. */
object NodeHealthUi {
    /** Group order from the contract; "phone" is computed in the app and always first. */
    const val PHONE = "phone"
    val GROUP_ORDER = listOf(PHONE, "node", "tv", "watcher", "pi", "network")

    enum class Colour { NORMAL, RED, AMBER, GREY }

    data class View(
        val problems: List<HealthItem>,
        val groups: List<Pair<String, List<HealthItem>>>,
        val total: Int,
        val level: HealthLevel,
        val summary: String,
    )

    fun groupTitle(group: String): String = when (group) {
        PHONE -> "This phone"
        "node" -> "Node"
        "tv" -> "TV"
        "watcher" -> "Watcher"
        "pi" -> "Raspberry Pi"
        "network" -> "Network"
        else -> group.replaceFirstChar { it.uppercase() }
    }

    /** Errors first, then warnings; order inside each kind is the node's. */
    fun problemsOf(items: List<HealthItem>): List<HealthItem> =
        items.filter { it.level == HealthLevel.ERROR } + items.filter { it.level == HealthLevel.WARN }

    /** INFO counts as OK; the worst level wins. */
    fun worst(items: List<HealthItem>): HealthLevel = when {
        items.any { it.level == HealthLevel.ERROR } -> HealthLevel.ERROR
        items.any { it.level == HealthLevel.WARN } -> HealthLevel.WARN
        else -> HealthLevel.OK
    }

    fun summary(problems: Int): String = when (problems) {
        0 -> "Everything is working"
        1 -> "1 problem"
        else -> "$problems problems"
    }

    fun lightsToggleText(count: Int, open: Boolean): String = if (open) "Hide status lights" else "Show all $count status lights"

    fun toggleText(total: Int, open: Boolean): String = if (open) "Hide indicators" else "Show all $total indicators"

    /** Stale data is never green: the colour is grey whatever the level was. */
    fun colour(level: HealthLevel, stale: Boolean): Colour = when {
        stale -> Colour.GREY
        level == HealthLevel.ERROR -> Colour.RED
        level == HealthLevel.WARN -> Colour.AMBER
        else -> Colour.NORMAL
    }

    /** The app's own reading: can this phone currently trust what it knows about the node? */
    fun connection(problem: NodeProblem?, stale: Boolean, sinceFetchMs: Long, vpn: Boolean, lastSeen: String): HealthItem = when {
        problem != null -> HealthItem(
            PHONE, "connection", "Node connection", "No contact", HealthLevel.ERROR, NodeUi.problemMessage(problem, vpn),
        )
        stale -> HealthItem(
            PHONE, "connection", "Node connection", "Out of date", HealthLevel.ERROR,
            "The node hasn't reported recently. Last seen $lastSeen.",
        )
        else -> HealthItem(PHONE, "connection", "Node connection", NodeUi.updatedLabel(sinceFetchMs), HealthLevel.OK, "")
    }

    /** What a row shows: the node's value, or "Last seen HH:MM" once its data is stale. */
    fun valueText(item: HealthItem, stale: Boolean, lastSeen: String): String =
        if (stale && item.group != PHONE) "Last seen $lastSeen" else item.value

    fun rowDescription(item: HealthItem, stale: Boolean, lastSeen: String): String {
        val base = "${item.label}, ${valueText(item, stale, lastSeen)}"
        val bad = !(stale && item.group != PHONE) && (item.level == HealthLevel.ERROR || item.level == HealthLevel.WARN)
        return if (!bad) base else if (item.detail.isBlank()) "$base, problem" else "$base, problem: ${item.detail}"
    }

    /**
     * [local] is the phone's own connection item. When the node data is stale its rows are greyed and neither
     * counted nor listed as problems: old readings must not raise or hide anything, only the connection error does.
     */
    fun build(local: HealthItem, node: NodeHealth?, stale: Boolean): View {
        val nodeItems = node?.items.orEmpty()
        val counted = if (stale) listOf(local) else listOf(local) + nodeItems
        val problems = problemsOf(counted)
        val byGroup = (listOf(local) + nodeItems).groupBy { it.group }
        val order = GROUP_ORDER + byGroup.keys.filter { it !in GROUP_ORDER }
        val groups = order.mapNotNull { g -> byGroup[g]?.let { g to it } }
        return View(problems, groups, byGroup.values.sumOf { it.size }, worst(counted), summary(problems.size))
    }

    // ---- Alerts ------------------------------------------------------------------------------------

    sealed class AlertDecision {
        object None : AlertDecision()
        object Clear : AlertDecision()
        data class Post(val text: String, val keys: Set<String>) : AlertDecision()
    }

    const val UNREACHABLE_KEY = "unreachable"
    const val UNREACHABLE_RUNS = 2

    /**
     * [health] null = the node did not answer. [unreachableStreak] counts this run. Alerts only when the set of
     * error keys is new (no repeats for the same set); clears once nothing is in error. An unanswered node
     * only counts on the Wi-Fi it was last seen on: elsewhere the owner is simply away.
     */
    fun shouldAlert(previousKeys: Set<String>, health: NodeHealth?, unreachableStreak: Int, sameWifi: Boolean): AlertDecision {
        if (health == null) {
            if (!sameWifi || unreachableStreak < UNREACHABLE_RUNS) return AlertDecision.None
            val keys = setOf(UNREACHABLE_KEY)
            return if (keys == previousKeys) AlertDecision.None else AlertDecision.Post("The node isn't answering", keys)
        }
        val errors = health.items.filter { it.level == HealthLevel.ERROR }
        if (errors.isEmpty()) return AlertDecision.Clear
        val keys = errors.map { it.key }.toSet()
        if (keys == previousKeys) return AlertDecision.None
        return AlertDecision.Post(errors.joinToString(" · ") { it.label }, keys)
    }
}

/**
 * Binds the visual health dashboard (banner, gauge grid, bar gauges, sparklines, redirects donut) into the
 * views of activity_node.xml. Views are created once and updated in place so TalkBack focus survives polling.
 */
class HealthDashboard(private val act: Activity) {
    private val d = act.resources.displayMetrics.density
    private fun dp(v: Int) = (v * d).toInt()
    private fun <T : View> f(id: Int): T = act.findViewById(id)

    private val tiles = NodeHealthVisual.TILES.associate {
        it.id to GaugeTileView(act).apply {
            kind = when (it.id) {
                NodeHealthVisual.WIFI -> GaugeTileView.Kind.BARS
                NodeHealthVisual.THROTTLE -> GaugeTileView.Kind.CIRCLE
                else -> GaugeTileView.Kind.RING
            }
        }
    }
    private val barGauges = NodeHealthVisual.BAR_GAUGES.associate { it.id to BarGaugeView(act) }
    private var gridSig = ""
    private var barSig = ""

    /** [reason] non-null = the node can't be trusted right now (stale or failed fetch): everything goes grey. */
    fun render(nodeItems: List<HealthItem>, visual: HealthVisual?, stale: Boolean, view: NodeHealthUi.View, reason: String?) {
        banner(Viz.banner(view.level, view.problems.size, reason), view.problems.isNotEmpty())
        val byId = nodeItems.associateBy { NodeHealthVisual.id(it) }

        // ring, throttling and Wi-Fi tiles
        val throttle = if (NodeHealthVisual.throttleShown(nodeItems, visual))
            Viz.throttleTile(byId[NodeHealthVisual.THROTTLE_NOW], byId[NodeHealthVisual.THROTTLE_BOOT], stale) else null
        val shown = NodeHealthVisual.TILES.filter {
            if (it.id == NodeHealthVisual.THROTTLE) throttle != null else visual?.metrics?.containsKey(it.id) == true && byId.containsKey(it.id)
        }
        shown.forEach { spec ->
            val tile = tiles.getValue(spec.id)
            if (spec.id == NodeHealthVisual.THROTTLE) { tile.setCircle(spec.label, throttle!!); return@forEach }
            val m = visual!!.metrics.getValue(spec.id)
            val item = byId.getValue(spec.id)
            val tone = Viz.toneOf(item.level, stale)
            val tt = Viz.tileText(spec.id, spec.label, m, item.level, visual.bars, stale)
            val word = Viz.statusWord(item.level, stale)
            if (spec.id == NodeHealthVisual.WIFI) {
                tile.set(spec.label, tt.value, tt.unit, word, tone, 0f, bars = if (stale) null else visual.bars, sub = tt.sub, description = tt.description)
            } else {
                tile.set(spec.label, tt.value, tt.unit, word, tone, if (stale) 0f else Viz.fraction(m), if (stale) emptyList() else Viz.tickFractions(m),
                    sub = tt.sub, description = tt.description)
            }
        }
        val gsig = shown.joinToString("|") { it.id }
        val grid = f<LinearLayout>(R.id.healthGrid)
        if (gsig != gridSig) {
            gridSig = gsig
            grid.removeAllViews()
            shown.chunked(2).forEach { pair ->
                val row = LinearLayout(act).apply { orientation = LinearLayout.HORIZONTAL }
                pair.forEachIndexed { i, spec ->
                    (tiles.getValue(spec.id).parent as? ViewGroup)?.removeView(tiles.getValue(spec.id))
                    row.addView(tiles.getValue(spec.id), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.MATCH_PARENT, 1f).apply {
                        if (i == 0) marginEnd = dp(6) else marginStart = dp(6)
                    })
                }
                if (pair.size == 1) row.addView(View(act).apply { importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO },
                    LinearLayout.LayoutParams(0, 1, 1f).apply { marginStart = dp(6) })
                grid.addView(row, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { bottomMargin = dp(12) })
            }
        }
        grid.visibility = if (shown.isEmpty()) View.GONE else View.VISIBLE

        // compact bar gauges
        val barShown = NodeHealthVisual.BAR_GAUGES.filter { visual?.metrics?.containsKey(it.id) == true && byId.containsKey(it.id) }
        barShown.forEach { spec ->
            val m = visual!!.metrics.getValue(spec.id)
            val item = byId.getValue(spec.id)
            val vt = if (stale) "—" else "${Viz.formatValue(m.value)} ${m.unit}".trim()
            barGauges.getValue(spec.id).set(spec.label, vt, Viz.statusWord(item.level, stale), Viz.toneOf(item.level, stale),
                if (stale) 0f else Viz.fraction(m), if (stale) emptyList() else Viz.tickFractions(m), Viz.gaugeDescription(spec.label, m, item.level, stale))
        }
        val bsig = barShown.joinToString("|") { it.id }
        val bbox = f<LinearLayout>(R.id.healthBarGauges)
        if (bsig != barSig) {
            barSig = bsig
            bbox.removeAllViews()
            barShown.forEach {
                val v = barGauges.getValue(it.id)
                (v.parent as? ViewGroup)?.removeView(v)
                bbox.addView(v, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(4) })
            }
        }
        bbox.visibility = if (barShown.isEmpty()) View.GONE else View.VISIBLE

        sparks(byId, visual, stale)
        redirects(byId, visual, stale)
    }

    private fun banner(b: Viz.Banner, tappable: Boolean) {
        val box = f<View>(R.id.healthBanner)
        box.background = GradientDrawable().apply { setColor(Viz.colour(b.tone)); cornerRadius = dp(40).toFloat() }
        f<TextView>(R.id.healthBannerGlyph).setIfChangedText(b.glyph)
        f<TextView>(R.id.healthBannerTitle).setIfChangedText(b.title)
        f<TextView>(R.id.healthBannerSub).setIfChangedText(b.subtitle)
        box.isClickable = tappable
        box.isFocusable = true
        val desc = Viz.bannerDescription(b, tappable)
        if (box.contentDescription != desc) box.contentDescription = desc
    }

    private fun sparks(byId: Map<String, HealthItem>, visual: HealthVisual?, stale: Boolean) {
        val box = f<View>(R.id.healthSparks)
        val h = visual?.history
        if (h == null) { box.visibility = View.GONE; return }
        box.visibility = View.VISIBLE
        data class S(val view: Int, val title: String, val id: String, val values: List<Double?>, val unit: String, val minSpan: Double)
        val all = listOf(
            S(R.id.sparkTemp, "Temperature", NodeHealthVisual.TEMP, h.temp, "°C", Viz.MIN_SPAN_TEMP),
            S(R.id.sparkCpu, "CPU use", NodeHealthVisual.CPU_USE, h.cpuUse, "%", Viz.MIN_SPAN_CPU),
            S(R.id.sparkWifi, "Wi-Fi signal", NodeHealthVisual.WIFI, h.wifiDbm, "dBm", Viz.MIN_SPAN_WIFI),
        )
        var any = false
        all.forEach { s ->
            val v = f<SparklineView>(s.view)
            val ok = Viz.sparkVisible(s.values)
            v.visibility = if (ok) View.VISIBLE else View.GONE
            if (!ok) return@forEach
            any = true
            val m = visual.metrics[s.id]
            val level = byId[s.id]?.level ?: HealthLevel.OK
            val unit = m?.unit?.ifEmpty { null } ?: s.unit
            v.set(s.title, s.values, m, unit, Viz.toneOf(level, stale), h.intervalS, stale, s.minSpan, Viz.sparkDescription(s.title, s.values, unit, level, stale))
        }
        f<View>(R.id.sparkEmpty).visibility = if (any) View.GONE else View.VISIBLE
    }

    private fun redirects(byId: Map<String, HealthItem>, visual: HealthVisual?, stale: Boolean) {
        val box = f<View>(R.id.healthRedirects)
        val c = visual?.redirects
        if (c == null || !byId.containsKey(NodeHealthVisual.REDIRECTS)) { box.visibility = View.GONE; return }
        box.visibility = View.VISIBLE
        f<DonutView>(R.id.redirectDonut).set(c, stale, Viz.donutDescription(c, stale))
        f<TextView>(R.id.redirectText).setIfChangedText(if (stale) "No data" else Viz.redirectsText(c))
    }

    private fun TextView.setIfChangedText(t: String) { if (text.toString() != t) text = t }
}
