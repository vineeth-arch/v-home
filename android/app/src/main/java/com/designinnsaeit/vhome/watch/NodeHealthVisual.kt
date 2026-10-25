package com.designinnsaeit.vhome.watch

import org.json.JSONArray
import org.json.JSONObject

/** `metric` of a health item (vnode-api-v1 "Visual fields"). Thresholds are absent for info-only readings. */
data class HealthMetric(
    val value: Double, val min: Double, val max: Double, val unit: String,
    val warn: Double?, val error: Double?, val higherIsWorse: Boolean,
)

data class RedirectCounts(val ok: Int, val failed: Int)

/** Last hour, oldest first, null where a reading was missing. Lists may be empty right after the node starts. */
data class HealthHistory(
    val intervalS: Int, val temp: List<Double?>, val cpuUse: List<Double?>, val load: List<Double?>,
    val memUsedMb: List<Double?>, val wifiDbm: List<Double?>,
)

/** The optional visual part of GET /v1/health. Every field may be missing (older node): then it is simply empty. */
data class HealthVisual(
    val metrics: Map<String, HealthMetric>,
    val bars: Int?,
    val redirects: RedirectCounts?,
    val history: HealthHistory?,
) {
    fun metric(group: String, key: String): HealthMetric? = metrics["$group/$key"]
}

object NodeHealthVisual {
    const val TEMP = "pi/temp"
    const val CPU_USE = "pi/cpu_use"
    const val CPU_LOAD = "pi/cpu_load"
    const val MEMORY = "pi/memory"
    const val DISK = "pi/disk"
    const val SWAP = "pi/swap"
    const val WIFI = "network/wifi_signal"
    const val VOLTAGE = "pi/voltage"
    const val CPU_FREQ = "pi/cpu_freq"
    const val REDIRECTS = "watcher/redirects"
    const val THROTTLE_NOW = "pi/throttle_now"
    const val THROTTLE_BOOT = "pi/throttle_boot"
    /** The Throttling tile is built from the two throttle items, not from a metric. */
    const val THROTTLE = "pi/throttle"

    data class Spec(val id: String, val label: String)

    /** Tiles in display order; the Wi-Fi tile (bars) is last. */
    val TILES = listOf(
        Spec(TEMP, "Temperature"), Spec(THROTTLE, "Throttling"), Spec(CPU_USE, "CPU use"), Spec(CPU_LOAD, "CPU load"),
        Spec(MEMORY, "Memory"), Spec(DISK, "Storage"), Spec(SWAP, "Swap"), Spec(WIFI, "Wi-Fi"),
    )
    val BAR_GAUGES = listOf(Spec(VOLTAGE, "Voltage"), Spec(CPU_FREQ, "CPU speed"))

    fun id(item: HealthItem) = "${item.group}/${item.key}"

    fun parse(o: JSONObject): HealthVisual {
        val metrics = LinkedHashMap<String, HealthMetric>()
        var bars: Int? = null
        var redirects: RedirectCounts? = null
        val arr = o.optJSONArray("items")
        for (i in 0 until (arr?.length() ?: 0)) {
            val it = arr!!.optJSONObject(i) ?: continue
            val id = "${it.optString("group")}/${it.optString("key")}"
            metric(it.optJSONObject("metric"))?.let { m -> metrics[id] = m }
            if (id == WIFI) {
                // The node puts bars inside metric; an item-level "bars" is accepted too.
                val src = listOfNotNull(it.optJSONObject("metric"), it).firstOrNull { o -> o.has("bars") && !o.isNull("bars") }
                if (src != null) bars = src.optInt("bars").coerceIn(0, 4)
            }
            if (id == REDIRECTS) it.optJSONObject("counts")?.let { c ->
                if (c.has("ok") || c.has("failed")) redirects = RedirectCounts(c.optInt("ok"), c.optInt("failed"))
            }
        }
        return HealthVisual(metrics, bars, redirects, history(o.optJSONObject("history")))
    }

    private fun num(o: JSONObject, k: String): Double? = if (!o.has(k) || o.isNull(k)) null else o.optDouble(k).takeIf { !it.isNaN() }

    private fun metric(m: JSONObject?): HealthMetric? {
        if (m == null) return null
        val v = num(m, "value") ?: return null
        val lo = num(m, "min") ?: return null
        val hi = num(m, "max") ?: return null
        if (hi <= lo) return null
        return HealthMetric(v, lo, hi, m.optString("unit"), num(m, "warn"), num(m, "error"), m.optBoolean("higher_is_worse", true))
    }

    private fun series(o: JSONObject, k: String): List<Double?> {
        val a: JSONArray = o.optJSONArray(k) ?: return emptyList()
        return (0 until a.length()).map { i -> if (a.isNull(i)) null else a.optDouble(i).takeIf { !it.isNaN() } }
    }

    private fun history(h: JSONObject?): HealthHistory? =
        h?.let { HealthHistory(it.optInt("interval_s", 30), series(it, "temp"), series(it, "cpu_use"), series(it, "load"), series(it, "mem_used_mb"), series(it, "wifi_dbm")) }

    /** An item is drawn as a gauge, bar or donut (not as a status light) when the node sent the data for it. */
    fun isVisual(item: HealthItem, v: HealthVisual?): Boolean {
        if (v == null) return false
        val id = id(item)
        return v.metrics.containsKey(id) || (id == REDIRECTS && v.redirects != null)
    }

    /** The Throttling tile needs the visual part of the health data and a readable "throttle now" item. */
    fun throttleShown(items: List<HealthItem>, v: HealthVisual?): Boolean =
        v != null && Viz.throttleTile(items.firstOrNull { id(it) == THROTTLE_NOW }, null, false) != null

    /** Items the Throttling tile already shows; they are not repeated as status lights. */
    fun throttleIds(items: List<HealthItem>, v: HealthVisual?): Set<String> =
        if (throttleShown(items, v)) setOf(THROTTLE_NOW, THROTTLE_BOOT) else emptySet()

    /** Status lights = everything without a visual (and not in [hidden]), grouped as the node orders them. */
    fun lights(groups: List<Pair<String, List<HealthItem>>>, v: HealthVisual?, hidden: Set<String> = emptySet()): List<Pair<String, List<HealthItem>>> =
        groups.map { (g, items) -> g to items.filter { !isVisual(it, v) && id(it) !in hidden } }.filter { it.second.isNotEmpty() }
}
