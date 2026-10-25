package com.designinnsaeit.vhome.watch

import java.time.Instant

/** Wording and small display decisions for NodeActivity, kept pure so the JVM tests can pin them down. */
object NodeUi {
    private const val VPN_NOTE = " A VPN is active; it can block local devices."
    const val UNKNOWN_RESULT = "No answer in time — check the status before trying again."

    fun problemMessage(p: NodeProblem, vpn: Boolean = false, pairing: Boolean = false): String = when (p) {
        NodeProblem.NOT_ON_WIFI -> "Not on Wi-Fi. The node is reachable only from home Wi-Fi." + if (vpn) VPN_NOTE else ""
        NodeProblem.VPN_ACTIVE -> VPN_NOTE.trim()
        NodeProblem.NO_ANSWER -> "The node didn't answer. You may be away from home, on a guest Wi-Fi that keeps devices apart, " +
            "or the node is off." + if (vpn) VPN_NOTE else ""
        NodeProblem.DIFFERENT_DEVICE -> "A different device answers at this address. Not trusting it."
        NodeProblem.PROTOCOL_MISMATCH -> "This app and the node are on different versions. Update the older one."
        NodeProblem.UNAUTHORIZED ->
            if (pairing) "That code didn't work. Check it, or run vnode pair-phone on the Pi for a new one."
            else "The node doesn't know this phone any more. Forget this node and pair again."
        NodeProblem.EXPIRED -> "That took too long to start. Try again."
        NodeProblem.DUPLICATE -> "The node already handled that. Check the status before trying again."
        NodeProblem.BUSY -> "The node is busy with something else. Wait a moment, then try again."
        NodeProblem.RATE_LIMITED ->
            if (pairing) "Too many tries. Run vnode pair-phone on the Pi for a new code."
            else "Too many requests. Wait a minute, then try again."
        NodeProblem.INVALID -> "The node didn't accept that. Check what you entered."
        NodeProblem.SERVER -> "The node had a problem. Try again in a moment, or look at Diagnostics."
    }

    /** A command that got no answer may still have happened, so it never reads as plain failure. */
    fun commandFailure(e: NodeException, vpn: Boolean): String =
        if (e.problem == NodeProblem.NO_ANSWER) UNKNOWN_RESULT else problemMessage(e.problem, vpn)

    fun launchText(r: CommandResult): String = when (r.outcome) {
        Outcome.CONFIRMED -> "V/HOME is on the TV"
        Outcome.ACCEPTED -> "The TV took the command; not seen in front yet"
        Outcome.FAILED -> "Couldn't open V/HOME" + r.detail.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()
        Outcome.UNKNOWN -> UNKNOWN_RESULT
    }

    fun commandText(r: CommandResult): String = when (r.outcome) {
        Outcome.CONFIRMED -> "Done."
        Outcome.ACCEPTED -> "Sent. The node will apply it shortly."
        Outcome.FAILED -> "That didn't work" + r.detail.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()
        Outcome.UNKNOWN -> UNKNOWN_RESULT
    }

    enum class Tone { GOOD, WAIT, BAD, QUIET }
    data class Hero(val title: String, val explain: String, val tone: Tone)

    private val POSITIVE = setOf("connected", "standby")

    fun title(headline: String): String = when (headline) {
        "connected" -> "Watching your TV"
        "standby" -> "TV in standby"
        "unreachable" -> "Can't reach the TV"
        "pairing_required" -> "TV not paired"
        "certificate_mismatch" -> "TV certificate changed"
        "permission_denied" -> "TV said no"
        "launcher_missing" -> "V/HOME not on the TV"
        "user_paused" -> "Paused"
        "safety_paused" -> "Paused for safety"
        "disabled" -> "Node isn't watching"
        else -> "Status unknown"
    }

    fun explain(headline: String): String = when (headline) {
        "connected" -> "Home on the TV opens V/HOME."
        "standby" -> "TV is in standby. The node keeps watching."
        "unreachable" -> "The node can't reach the TV. It may be off."
        "pairing_required" -> "The node isn't paired with the TV yet. Pair it below."
        "certificate_mismatch" -> "The TV doesn't look like the one the node paired with. If the TV was reset, pair it again below."
        "permission_denied" -> "The TV refused the node. Pair the TV again and accept the prompt on the TV."
        "launcher_missing" -> "The TV doesn't have V/HOME installed, so there is nothing to open."
        "user_paused" -> "Watching is paused. Home won't open V/HOME until you resume."
        "safety_paused" -> "Paused after repeated failures. Check the TV, then resume."
        "disabled" -> "The node isn't watching. This phone or nobody is."
        else -> "The node can't tell what the TV is doing yet."
    }

    fun problemTitle(p: NodeProblem): String = when (p) {
        NodeProblem.NOT_ON_WIFI -> "Not on Wi-Fi"
        NodeProblem.NO_ANSWER, NodeProblem.VPN_ACTIVE -> "Can't reach the node"
        NodeProblem.DIFFERENT_DEVICE -> "Not your node"
        NodeProblem.UNAUTHORIZED -> "Not paired any more"
        NodeProblem.PROTOCOL_MISMATCH -> "Versions differ"
        else -> "Node problem"
    }

    fun problemTone(p: NodeProblem): Tone = when (p) {
        NodeProblem.DIFFERENT_DEVICE, NodeProblem.UNAUTHORIZED, NodeProblem.PROTOCOL_MISMATCH -> Tone.BAD
        else -> Tone.WAIT
    }

    fun tone(headline: String): Tone = when (headline) {
        "connected" -> Tone.GOOD
        "standby", "user_paused" -> Tone.QUIET
        "unreachable", "safety_paused", "disabled", "unknown" -> Tone.WAIT
        else -> Tone.BAD
    }

    /**
     * Old data must never read as live: past [NODE_STALE_MS] since the last fetch everything is stale; a
     * "watching" headline is also stale when the node's own TV observation is old or missing.
     */
    fun isStale(headline: String, fetchedAt: Long, now: Long, tvAgeS: Double?): Boolean =
        NodeRules.isStale(fetchedAt, now, 0.0) || (headline in POSITIVE && NodeRules.isStale(fetchedAt, now, tvAgeS))

    fun hero(s: NodeStatus, stale: Boolean, lastSeen: String): Hero =
        if (stale) Hero("Last seen $lastSeen", "The node hasn't reported recently, so this may not be true now.", Tone.QUIET)
        else Hero(title(s.headline), explain(s.headline), tone(s.headline))

    fun updatedLabel(sinceFetchMs: Long): String {
        val s = (sinceFetchMs / 1000).coerceAtLeast(0)
        return when {
            s < 2 -> "Updated just now"
            s < 60 -> "Updated $s s ago"
            else -> "Updated ${s / 60} min ago"
        }
    }

    fun tvStateLabel(state: String, stale: Boolean, lastSeen: String): String =
        if (stale && state in POSITIVE) "Last seen $lastSeen" else when (state) {
            "connected" -> "Connected"
            "standby" -> "Standby"
            "unreachable" -> "Can't reach it"
            "pairing_required" -> "Not paired"
            "certificate_mismatch" -> "Certificate changed"
            "permission_denied" -> "Refused the node"
            "launcher_missing" -> "V/HOME missing"
            else -> "Unknown"
        }

    fun watcherStateLabel(state: String): String = when (state) {
        "watching" -> "Watching"
        "user_paused" -> "Paused by you"
        "safety_paused" -> "Paused for safety"
        "disabled" -> "Off (handed to a phone)"
        else -> "Not ready"
    }

    fun pairingText(state: String, detail: String): String? = when (state) {
        "waiting_prompt" -> "Accept the prompt on the TV."
        "done" -> "The TV is paired."
        "failed" -> "Pairing failed" + detail.takeIf { it.isNotBlank() }?.let { ": $it" }.orEmpty()
        else -> null
    }

    /** Re-pinning is only offered when the TV's certificate actually changed. */
    fun showRepin(tvState: String): Boolean = tvState == "certificate_mismatch"

    /** Resume when watching is paused or stopped by the safety stop; otherwise offer a one-hour pause. */
    fun showResume(watcherState: String, paused: Boolean): Boolean =
        paused || watcherState == "user_paused" || watcherState == "safety_paused"

    fun showTurnOn(watcherState: String): Boolean = watcherState == "disabled"

    fun throttledText(hex: String?): String = when {
        hex == null -> "Unknown"
        runCatching { java.lang.Long.decode(hex) }.getOrNull() == 0L -> "None"
        else -> "Yes — check the power supply"
    }

    fun mbText(mb: Int): String = if (mb >= 1024) String.format("%.1f GB", mb / 1024.0) else "$mb MB"

    fun durationText(s: Long): String {
        val m = s / 60
        return when {
            s < 60 -> "$s s"
            m < 60 -> "$m min"
            m < 24 * 60 -> "${m / 60} h ${m % 60} min"
            else -> "${m / (24 * 60)} d ${m % (24 * 60) / 60} h"
        }
    }

    fun wifiText(bars: Int?, dbm: Int?): String = when {
        bars == null && dbm == null -> "Unknown"
        else -> listOfNotNull(bars?.let { "$it bars" }, dbm?.let { "$it dBm" }).joinToString(" · ")
    }

    fun latencyText(s: Double?): String = s?.let { String.format("%.1f s", it) } ?: "—"

    fun parseInstantMs(iso: String?): Long? = iso?.let { runCatching { Instant.parse(it).toEpochMilli() }.getOrNull() }

    /** The pairing code as the Pi prints it (XXXX-XXXX), reduced to the 8 characters the node expects. */
    fun normalizeCode(raw: String): String = raw.uppercase().filter { it.isLetterOrDigit() }
        .replace('O', '0').replace('I', '1').replace('L', '1')

    fun codeLooksComplete(raw: String): Boolean = normalizeCode(raw).length == 8
}
