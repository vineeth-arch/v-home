package com.designinnsaeit.vhome.watch

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
