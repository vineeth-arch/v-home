package com.designinnsaeit.vhome.watch

import org.json.JSONObject

// VNode shared contract (Wave 0). Mirrors docs/contracts/vnode-api-v1.md. Agents consume it; changes go
// through the orchestrator.

const val NODE_API = 1
const val NODE_PORT = 8443
const val NODE_SERVICE_TYPE = "_vhome._tcp."
/** Older than this (phone elapsed clock + node age_s) = stale: show "Last seen", never "Watching". */
const val NODE_STALE_MS = 20_000L

/** Who watches the TV. STANDALONE = this phone's WatcherService (the pre-VNode behaviour). */
enum class ControllerMode { STANDALONE, VNODE }

enum class Outcome { ACCEPTED, CONFIRMED, FAILED, UNKNOWN }

data class CommandResult(val outcome: Outcome, val detail: String) {
    companion object {
        fun parse(o: JSONObject) = CommandResult(
            runCatching { Outcome.valueOf(o.optString("outcome").uppercase()) }.getOrDefault(Outcome.UNKNOWN),
            o.optString("detail"),
        )
    }
}

data class NodeInfo(val api: Int, val nodeId: String, val name: String, val version: String, val capabilities: Map<String, String>) {
    companion object {
        fun parse(o: JSONObject): NodeInfo {
            val caps = o.optJSONObject("capabilities") ?: JSONObject()
            return NodeInfo(
                o.optInt("api", -1), o.optString("node_id"), o.optString("name"), o.optString("version"),
                caps.keys().asSequence().associateWith { caps.optString(it) },
            )
        }
    }
}

private fun JSONObject.optDoubleOrNull(k: String): Double? = if (isNull(k) || !has(k)) null else optDouble(k)
private fun JSONObject.optStringOrNull(k: String): String? = if (isNull(k) || !has(k)) null else optString(k)

data class NodeStatus(
    val headline: String,
    val nodeVersion: String, val nodeUptimeS: Long,
    val tvState: String, val tvHost: String?, val tvPower: String?, val tvForeground: String?,
    val tvAgeS: Double?, val tvLastError: String?, val pairingState: String, val pairingDetail: String,
    val watcherState: String, val enabled: Boolean, val paused: Boolean, val pausedUntil: String?,
    val redirects: Int, val lastLatencyS: Double?, val lastFailure: String?,
) {
    companion object {
        fun parse(o: JSONObject): NodeStatus {
            val n = o.optJSONObject("node") ?: JSONObject()
            val t = o.optJSONObject("tv") ?: JSONObject()
            val p = t.optJSONObject("pairing") ?: JSONObject()
            val w = o.optJSONObject("watcher") ?: JSONObject()
            return NodeStatus(
                o.optString("headline", "unknown"), n.optString("version"), n.optLong("uptime_s"),
                t.optString("state", "unknown"), t.optStringOrNull("host"), t.optStringOrNull("power"),
                t.optStringOrNull("foreground"), t.optDoubleOrNull("age_s"), t.optStringOrNull("last_error"),
                p.optString("state", "idle"), p.optString("detail"),
                w.optString("state", "not_ready"), w.optBoolean("enabled", true), w.optBoolean("paused"),
                w.optStringOrNull("paused_until"), w.optInt("redirects"), w.optDoubleOrNull("last_latency_s"),
                w.optStringOrNull("last_failure"),
            )
        }
    }
}

data class DeviceStatus(
    val tempC: Double?, val throttled: String?, val memUsedMb: Int, val memTotalMb: Int, val diskFreeMb: Int,
    val uptimeS: Long, val wifiDbm: Int?, val wifiBars: Int?,
    val ledsAvailable: Boolean, val ledsEnabled: Boolean, val ledsBrightness: Int, val ledsThermalOff: Boolean,
) {
    companion object {
        fun parse(o: JSONObject): DeviceStatus {
            val wifi = o.optJSONObject("wifi")
            val leds = o.optJSONObject("leds")
            return DeviceStatus(
                o.optDoubleOrNull("temp_c"), o.optStringOrNull("throttled"), o.optInt("mem_used_mb"),
                o.optInt("mem_total_mb"), o.optInt("disk_free_mb"), o.optLong("uptime_s"),
                wifi?.takeIf { it.has("dbm") && !it.isNull("dbm") }?.optInt("dbm"),
                wifi?.takeIf { it.has("bars") && !it.isNull("bars") }?.optInt("bars"),
                leds != null, leds?.optBoolean("enabled") ?: false, leds?.optInt("brightness", 2) ?: 2,
                leds?.optBoolean("thermal_off") ?: false,
            )
        }
    }
}

/** Failure kinds the app explains separately. */
enum class NodeProblem { NOT_ON_WIFI, VPN_ACTIVE, NO_ANSWER, DIFFERENT_DEVICE, PROTOCOL_MISMATCH, UNAUTHORIZED, EXPIRED, DUPLICATE, BUSY, RATE_LIMITED, INVALID, SERVER }

class NodeException(val problem: NodeProblem, msg: String) : Exception(msg)

object NodeRules {
    /**
     * Age of what the node reported, measured without comparing phone and node wall clocks:
     * phone-side time since the fetch + node-side age_s. Null = never observed.
     */
    fun observedAgeMs(fetchedAtElapsed: Long, nowElapsed: Long, ageS: Double?): Long? =
        ageS?.let { (nowElapsed - fetchedAtElapsed).coerceAtLeast(0) + (it * 1000).toLong() }

    fun isStale(fetchedAtElapsed: Long, nowElapsed: Long, ageS: Double?): Boolean =
        observedAgeMs(fetchedAtElapsed, nowElapsed, ageS)?.let { it > NODE_STALE_MS } ?: true

    /**
     * The phone may start its own watcher only when the node confirmed it stopped watching, or the owner
     * explicitly confirmed the node is unplugged/disconnected. Never automatically on "node unreachable".
     */
    fun canSwitchToStandalone(nodeConfirmedDisabled: Boolean, ownerConfirmedDisconnected: Boolean): Boolean =
        nodeConfirmedDisabled || ownerConfirmedDisconnected

    /** "3f9a 1c2e 88b0 7d41 02aa 9c11" — the first 24 hex chars (96 bits) in groups of 4, for comparing with `vnode pair-phone`. */
    fun fingerprintGroups(nodeId: String): String = nodeId.lowercase().take(24).chunked(4).joinToString(" ")
}
