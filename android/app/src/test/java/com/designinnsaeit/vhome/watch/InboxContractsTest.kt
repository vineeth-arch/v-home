package com.designinnsaeit.vhome.watch

import java.io.File
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InboxContractsTest {
    @Test fun keyFormat() {
        val k = InboxRules.newKey()
        assertTrue(k, InboxRules.isValidKey(k))
        assertEquals(35, k.length)
        assertNotEquals(k, InboxRules.newKey())
        assertTrue(InboxRules.isValidKey(InboxRules.newKey(UUID(0, 1))))
        assertFalse(InboxRules.isValidKey("short"))
        assertFalse(InboxRules.isValidKey("a".repeat(65)))
        assertFalse(InboxRules.isValidKey("has space has space!"))
    }

    @Test fun urlDetection() {
        assertEquals("url", InboxRules.detectKind("https://example.com/a?b=1"))
        assertEquals("url", InboxRules.detectKind("  http://x.io  "))
        assertEquals("text", InboxRules.detectKind("see https://example.com"))
        assertEquals("text", InboxRules.detectKind("https://a.com https://b.com"))
        assertEquals("text", InboxRules.detectKind("ftp://x.com"))
        assertEquals("text", InboxRules.detectKind("hello"))
    }

    @Test fun textCapIsInBytes() {
        assertEquals(InboxRules.Check.EMPTY, InboxRules.check("  \n"))
        assertEquals(InboxRules.Check.OK, InboxRules.check("a".repeat(8192)))
        assertEquals(InboxRules.Check.TOO_LARGE, InboxRules.check("a".repeat(8193)))
        assertEquals(InboxRules.Check.TOO_LARGE, InboxRules.check("é".repeat(4097))) // 2 bytes each
        assertEquals("5 / 8192 bytes", InboxRules.counter("hello"))
    }

    @Test fun errorCodesMapToPlainMessages() {
        assertEquals("VNode queue is full, try later", InboxRules.errorMessage(429, "queue_full"))
        assertEquals("Inbox service is off on VNode", InboxRules.errorMessage(503, "integrations_unavailable"))
        assertEquals("Inbox service is off on VNode", InboxRules.errorMessage(503, null))
        assertEquals("Phone not paired", InboxRules.errorMessage(401, null))
        assertEquals("Phone not paired", InboxRules.errorMessage(401, "unauthorized"))
        assertEquals(InboxRules.errorMessage(null, "too_large"), InboxRules.errorMessage(413, null))
        assertEquals(InboxRules.errorMessage(null, "disk_reserve"), InboxRules.errorMessage(507, null))
        assertEquals(InboxRules.errorMessage(null, "unsupported_kind"), InboxRules.errorMessage(415, null))
        assertTrue(InboxRules.errorMessage(409, "key_conflict").contains("different text"))
        assertEquals("Not delivered (HTTP 500)", InboxRules.errorMessage(500, null))
        assertEquals("VNode doesn't have the Inbox yet. Update VNode with --with-integrations.", InboxRules.errorMessage(404, "not_found"))
        assertEquals("Not delivered (HTTP ?)", InboxRules.errorMessage(null, null))
    }

    @Test fun statusLabelsNeverSayProcessed() {
        assertEquals("Accepted by Brain", InboxRules.statusLabel("completed"))
        assertEquals("Queued", InboxRules.statusLabel("queued"))
        assertEquals("Sending…", InboxRules.statusLabel("claimed"))
        assertEquals("Sending…", InboxRules.statusLabel("processing"))
        assertEquals("Failed", InboxRules.statusLabel("failed"))
        assertEquals("Cancelled", InboxRules.statusLabel("cancelled"))
        assertEquals("Unknown", InboxRules.statusLabel("unknown"))
        assertEquals("Unknown", InboxRules.statusLabel("something_new"))
        assertEquals("Sent to VNode", InboxRules.SENT_LABEL)
        listOf("queued", "claimed", "processing", "completed", "failed", "cancelled", "unknown", "x").forEach {
            assertFalse(InboxRules.statusLabel(it).contains("processed", ignoreCase = true))
        }
    }

    @Test fun byKeyDecisionTable() {
        assertEquals(ByKeyDecision.SENT, InboxRules.byKeyDecision(200))
        assertEquals(ByKeyDecision.RESEND_SAFE, InboxRules.byKeyDecision(404))
        listOf(null, 201, 401, 429, 500, 503).forEach { assertEquals("$it", ByKeyDecision.KEEP_DRAFT, InboxRules.byKeyDecision(it)) }
    }

    @Test fun cancelAndRetryRules() {
        fun job(status: String, safe: Boolean) = InboxJob("j1", "text", "", status, "", 0, null, null, null, safe)
        assertTrue(job("queued", false).canCancel)
        assertFalse(job("claimed", false).canCancel)
        assertTrue(job("failed", true).canRetry)
        assertFalse(job("failed", false).canRetry)
        assertFalse(job("queued", true).canRetry)
    }

    @Test fun brainStatusParsesAndStaleIsNeverGreen() {
        val fresh = BrainStatus.parse(JSONObject("""{"snapshot":{"reachable":true,"pending":2,"processed_today":5,"needs_review":0,"failed":0},
            "snapshot_age_s":10,"stale":false,"worker_last_seen_age_s":4,"worker_stale":false,"queue":{"queued":1,"completed":3}}"""))
        assertEquals(2, fresh.pending); assertEquals(5, fresh.processedToday); assertEquals(3, fresh.queue!!.completed)
        assertEquals("Brain reachable", InboxRules.brainHeadline(fresh))
        assertEquals(NodeHealthUi.Colour.NORMAL, NodeHealthUi.colour(InboxRules.brainLevel(fresh), InboxRules.brainStale(fresh)))

        val workerGone = BrainStatus.parse(JSONObject("""{"snapshot":{"reachable":true},"snapshot_age_s":10,"stale":false,"worker_stale":true,"queue":{}}"""))
        assertEquals("Mac not reporting", InboxRules.brainHeadline(workerGone))
        assertEquals(NodeHealthUi.Colour.GREY, NodeHealthUi.colour(InboxRules.brainLevel(workerGone), InboxRules.brainStale(workerGone)))

        val none = BrainStatus.parse(JSONObject("""{"snapshot":null,"stale":true,"worker_stale":false,"queue":{}}"""))
        assertFalse(none.hasSnapshot); assertNull(none.pending)
        assertEquals(NodeHealthUi.Colour.GREY, NodeHealthUi.colour(InboxRules.brainLevel(none), InboxRules.brainStale(none)))
        assertEquals("never", InboxRules.ageText(null))
    }
}

class InboxStatusTest {
    @Test fun missingCountsAreUnknownNotEmpty() {
        assertNull(InboxCounts.parse(null))
        assertEquals(0, InboxCounts.parse(JSONObject("{}"))!!.queued)
    }

    @Test fun missingReachableIsInfoNeverOk() {
        val b = BrainStatus.parse(JSONObject("""{"snapshot":{"pending":1},"stale":false,"worker_stale":false,"queue":{}}"""))
        assertEquals(HealthLevel.INFO, InboxRules.brainLevel(b))
    }

    @Test fun modeAndAuthErrorAreSurfaced() {
        val b = BrainStatus.parse(JSONObject("""{"snapshot":{"reachable":true,"mode":"dry_run","auth_error":true},"stale":false,"worker_stale":false,"queue":{}}"""))
        assertEquals("Mac worker in dry run — nothing is delivered", InboxRules.dryRunNotice(b))
        assertEquals("Brain rejected the worker token", InboxRules.authNotice(b))
        assertEquals(HealthLevel.ERROR, InboxRules.brainLevel(b))
        val live = BrainStatus.parse(JSONObject("""{"snapshot":{"reachable":true,"mode":"live"},"queue":{}}"""))
        assertNull(InboxRules.dryRunNotice(live)); assertNull(InboxRules.authNotice(live))
    }
}

class InboxTruncateTest {
    @Test fun shortTextUntouched() = assertEquals("hi" to false, InboxRules.truncateUtf8("hi"))

    @Test fun cutsAtByteCapWithoutSplittingCharacters() {
        val text = "€".repeat(5000) // 3 bytes each = 15000 bytes
        val (cut, was) = InboxRules.truncateUtf8(text)
        assertTrue(was)
        assertTrue(InboxRules.bytes(cut) <= InboxRules.MAX_TEXT_BYTES)
        assertEquals(8190, InboxRules.bytes(cut)) // 2730 whole characters, not 2730.67
        assertTrue(cut.all { it == '€' })
        val emoji = "😀".repeat(5000) // 4 bytes each, surrogate pairs
        val (e, _) = InboxRules.truncateUtf8(emoji)
        assertEquals(8192, InboxRules.bytes(e)); assertTrue(e.all { it != '\uFFFD' })
    }

    @Test fun hugeAsciiIsCut() {
        val (cut, was) = InboxRules.truncateUtf8("a".repeat(1_000_000))
        assertTrue(was); assertEquals(8192, cut.length)
    }

    @Test fun exactCapIsNotCut() = assertFalse(InboxRules.truncateUtf8("a".repeat(8192)).second)

    @Test fun ambiguousServerErrors() {
        assertTrue(listOf(500, 502, 504).all { InboxRules.isAmbiguousServerError(it) })
        assertFalse(listOf(429, 503, 507, 404).any { InboxRules.isAmbiguousServerError(it) })
    }
}

class DraftStoreTest {
    private fun d(i: Int, text: String = "t$i") = Draft(InboxRules.newKey(UUID(0, i.toLong())), text, "text", i.toLong())

    @Test fun twentyFirstDropsOldest() {
        val list = (1..21).map { d(it) }
        val (kept, dropped) = DraftStore.enforce(list)
        assertEquals(20, kept.size); assertEquals(1, dropped)
        assertEquals("t2", kept.first().text); assertEquals("t21", kept.last().text)
    }

    @Test fun byteCapDropsOldest() {
        val big = "a".repeat(8192)
        val list = (1..40).map { d(it, big) } // would be 320 KB, but also count-capped: use a high count cap
        val (kept, _) = DraftStore.enforce(list, maxCount = 100)
        assertEquals(300 * 1024 / 8192, kept.size) // 37 x 8 KB = 296 KB
        assertEquals(40L, kept.last().createdAt)
    }

    @Test fun newestAlwaysStays() {
        val (kept, dropped) = DraftStore.enforce(listOf(d(1, "a".repeat(100))), maxBytes = 10)
        assertEquals(1, kept.size); assertEquals(0, dropped)
    }

    @Test fun persistsKeyAcrossReloadsAndRemoves() {
        val f = File.createTempFile("drafts", ".json").apply { delete(); deleteOnExit() }
        val s = DraftStore(f)
        val a = s.add("https://example.com")
        assertEquals("url", a.draft.kind)
        assertEquals(0, a.dropped)
        // A fresh store over the same file sees the same draft and the same idempotency key (stable across resends).
        val again = DraftStore(f).all().single()
        assertEquals(a.draft.key, again.key)
        assertTrue(InboxRules.isValidKey(again.key))
        s.remove(again.key)
        assertTrue(DraftStore(f).all().isEmpty())
    }

    @Test fun twentyFirstThroughStore() {
        val f = File.createTempFile("drafts", ".json").apply { delete(); deleteOnExit() }
        val s = DraftStore(f)
        (1..20).forEach { s.add("n$it", now = it.toLong()) }
        val last = s.add("n21", now = 21)
        assertEquals(1, last.dropped)
        assertEquals(20, s.all().size)
        assertEquals("n2", s.all().first().text)
    }

    @Test fun damagedFileIsEmptyAndKeptAsBak() {
        val f = File.createTempFile("drafts", ".json").apply { writeText("{not json"); deleteOnExit() }
        val bak = File(f.parentFile, f.name + ".bak").apply { deleteOnExit() }
        assertTrue(DraftStore(f).all().isEmpty())
        assertEquals("{not json", bak.readText())
        assertFalse(f.exists())
    }

    @Test fun saveReportsFailure() {
        val dir = File.createTempFile("drafts", "d").apply { delete(); mkdir(); deleteOnExit() }
        val s = DraftStore(File(dir, "missing/sub/drafts.json")) // parent does not exist
        assertFalse(s.add("x").saved)
    }
}
