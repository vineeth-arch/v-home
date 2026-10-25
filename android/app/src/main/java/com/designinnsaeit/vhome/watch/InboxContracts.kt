package com.designinnsaeit.vhome.watch

import java.util.UUID
import org.json.JSONObject

/** Job as the phone sees it (vnode-int-api-v1 "Job"); the payload is never sent back. */
data class InboxJob(
    val id: String, val kind: String, val label: String, val status: String, val createdAt: String,
    val attempts: Int, val resultRef: String?, val errorCode: String?, val errorMsg: String?, val retrySafe: Boolean,
) {
    val canCancel get() = status == "queued"
    val canRetry get() = status == "failed" && retrySafe

    companion object {
        fun parse(o: JSONObject): InboxJob? {
            val id = o.optString("id")
            if (id.isEmpty()) return null
            fun s(k: String): String? = if (o.has(k) && !o.isNull(k)) o.optString(k).ifEmpty { null } else null
            return InboxJob(
                id, o.optString("kind"), o.optString("label"), o.optString("status"), o.optString("created_at"),
                o.optInt("attempts"), s("result_ref"), s("error_code"), s("error_msg"), o.optBoolean("retry_safe"),
            )
        }
    }
}

data class InboxCounts(val queued: Int, val claimed: Int, val processing: Int, val unknown: Int, val completed: Int, val failed: Int, val cancelled: Int) {
    companion object {
        /** null = VNode sent no counts (unknown), which is not the same as an empty queue. */
        fun parse(o: JSONObject?): InboxCounts? = o?.let {
            InboxCounts(
                it.optInt("queued"), it.optInt("claimed"), it.optInt("processing"), it.optInt("unknown"),
                it.optInt("completed"), it.optInt("failed"), it.optInt("cancelled"),
            )
        }
    }
}

/**
 * GET /v1/inbox/brain-status. The snapshot is whatever the Mac worker reported; its field names are not fixed by the
 * contract, so every field is optional (null = not reported).
 */
data class BrainStatus(
    val hasSnapshot: Boolean, val snapshotAgeS: Int?, val stale: Boolean, val workerSeenAgeS: Int?, val workerStale: Boolean,
    val queue: InboxCounts?, val reachable: Boolean?, val heartbeat: String?,
    val pending: Int?, val processedToday: Int?, val needsReview: Int?, val failed: Int?,
    val mode: String? = null, val authError: Boolean = false,
) {
    companion object {
        fun parse(o: JSONObject): BrainStatus {
            fun age(k: String): Int? = if (o.has(k) && !o.isNull(k)) o.optInt(k) else null
            val snap = o.optJSONObject("snapshot")
            fun n(k: String): Int? = if (snap != null && snap.has(k) && !snap.isNull(k)) snap.optInt(k) else null
            return BrainStatus(
                snap != null, age("snapshot_age_s"), o.optBoolean("stale", true), age("worker_last_seen_age_s"),
                o.optBoolean("worker_stale", true), InboxCounts.parse(o.optJSONObject("queue")),
                if (snap != null && snap.has("reachable") && !snap.isNull("reachable")) snap.optBoolean("reachable") else null,
                snap?.takeIf { it.has("heartbeat") && !it.isNull("heartbeat") }?.optString("heartbeat"),
                n("pending"), n("processed_today"), n("needs_review"), n("failed"),
                snap?.takeIf { it.has("mode") && !it.isNull("mode") }?.optString("mode"), snap?.optBoolean("auth_error") ?: false,
            )
        }
    }
}

/** What to do after a submit whose outcome is unknown (timeout / IO error), decided from GET /by-key/{key}. */
enum class ByKeyDecision { SENT, RESEND_SAFE, KEEP_DRAFT }

object InboxRules {
    const val MAX_TEXT_BYTES = 8 * 1024
    const val MAX_DRAFTS = 20
    const val MAX_DRAFT_BYTES = 300 * 1024
    private val URL = Regex("^https?://\\S+$")
    private val KEY = Regex("^[A-Za-z0-9_-]{16,64}$")

    /** One key per draft, made once and reused on every resend: "vh-" + 32 hex = 35 chars. */
    fun newKey(u: UUID = UUID.randomUUID()): String = "vh-" + u.toString().replace("-", "")
    fun isValidKey(k: String) = KEY.matches(k)

    fun detectKind(text: String): String = if (URL.matches(text.trim())) "url" else "text"
    fun bytes(text: String): Int = text.toByteArray(Charsets.UTF_8).size

    /** Cuts [text] to at most [maxBytes] UTF-8 bytes without splitting a character. Returns (text, wasCut). */
    fun truncateUtf8(text: String, maxBytes: Int = MAX_TEXT_BYTES): Pair<String, Boolean> {
        // A UTF-8 string of N chars is at most 3N bytes (4 per surrogate pair = 2 chars), so this cheap bound avoids encoding huge input.
        val head = if (text.length > maxBytes) text.substring(0, maxBytes) else text
        val b = head.toByteArray(Charsets.UTF_8)
        if (b.size <= maxBytes && head.length == text.length) return text to false
        var end = minOf(maxBytes, b.size)
        if (end < b.size) while (end > 0 && (b[end].toInt() and 0xC0) == 0x80) end-- // back up to a character start
        return String(b, 0, end, Charsets.UTF_8) to true
    }

    /** 5xx other than 503/507 may have been stored before failing: resolve by key like a dropped connection. */
    fun isAmbiguousServerError(http: Int): Boolean = http in 500..599 && http != 503 && http != 507

    enum class Check { OK, EMPTY, TOO_LARGE }
    fun check(text: String): Check = when {
        text.isBlank() -> Check.EMPTY
        bytes(text) > MAX_TEXT_BYTES -> Check.TOO_LARGE
        else -> Check.OK
    }
    fun counter(text: String) = "${bytes(text)} / $MAX_TEXT_BYTES bytes"

    /** Server job status -> chip text. "completed" only means Brain's inbox took it, never that it was processed. */
    fun statusLabel(status: String): String = when (status) {
        "queued" -> "Queued"
        "claimed", "processing" -> "Sending…"
        "completed" -> "Accepted by Brain"
        "failed" -> "Failed"
        "cancelled" -> "Cancelled"
        else -> "Unknown" // includes "unknown" and anything new
    }
    const val SENT_LABEL = "Sent to VNode"

    enum class Tone { GOOD, WAIT, BAD, QUIET }
    fun statusTone(status: String): Tone = when (status) {
        "completed" -> Tone.GOOD
        "queued", "claimed", "processing" -> Tone.WAIT
        "failed" -> Tone.BAD
        else -> Tone.QUIET
    }

    /** Short plain message for an error code (preferred) or HTTP status. */
    fun errorMessage(http: Int?, code: String?): String = when (code) {
        "queue_full" -> "VNode queue is full, try later"
        "disk_reserve" -> "VNode is low on disk space"
        "too_large" -> "Too large for VNode (8 KB max)"
        "unsupported_kind" -> "VNode doesn't accept this kind"
        "key_conflict" -> "This draft was already sent with different text"
        "integrations_unavailable" -> "Inbox service is off on VNode"
        "rate_limited" -> "Sending too fast, wait a minute"
        "not_cancellable" -> "Only queued items can be cancelled"
        "not_retryable" -> "This item can't be retried"
        "duplicate", "expired" -> "Request expired, try again"
        else -> when (http) {
            401 -> "Phone not paired"
            413 -> errorMessage(null, "too_large")
            415 -> errorMessage(null, "unsupported_kind")
            429 -> errorMessage(null, "rate_limited")
            503 -> errorMessage(null, "integrations_unavailable")
            507 -> errorMessage(null, "disk_reserve")
            else -> "Not delivered (HTTP ${http ?: "?"})"
        }
    }

    /** 200 = stored; 404 = never stored (resend with the SAME key); anything else (or no answer) = stay a draft. */
    fun byKeyDecision(http: Int?): ByKeyDecision = when (http) {
        200 -> ByKeyDecision.SENT
        404 -> ByKeyDecision.RESEND_SAFE
        else -> ByKeyDecision.KEEP_DRAFT
    }

    // ---- Brain status wording -----------------------------------------------------------------------

    fun brainLevel(b: BrainStatus): HealthLevel = when {
        !b.hasSnapshot -> HealthLevel.INFO
        b.reachable == false || b.authError -> HealthLevel.ERROR
        (b.failed ?: 0) > 0 || (b.needsReview ?: 0) > 0 -> HealthLevel.WARN
        b.reachable == null -> HealthLevel.INFO // a snapshot that does not say whether Brain is reachable is never "OK"
        else -> HealthLevel.OK
    }

    /** Stale data is never green: it greys out via NodeHealthUi.colour. */
    fun brainStale(b: BrainStatus) = b.stale || b.workerStale

    fun brainHeadline(b: BrainStatus): String = when {
        b.workerStale -> "Mac not reporting"
        !b.hasSnapshot -> "No Brain report yet"
        b.stale -> "Brain report is out of date"
        b.reachable == false -> "Brain not reachable"
        b.reachable == true -> "Brain reachable"
        else -> "Brain status reported"
    }

    fun dryRunNotice(b: BrainStatus): String? = if (b.mode == "dry_run") "Mac worker in dry run — nothing is delivered" else null
    fun authNotice(b: BrainStatus): String? = if (b.authError) "Brain rejected the worker token" else null

    fun ageText(s: Int?): String = if (s == null) "never" else NodeUi.durationText(s.toLong()) + " ago"
}
