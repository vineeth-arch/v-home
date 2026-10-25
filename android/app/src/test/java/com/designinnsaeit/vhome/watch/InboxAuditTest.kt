package com.designinnsaeit.vhome.watch

import java.io.ByteArrayInputStream
import java.io.File
import java.util.UUID
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class InboxAuditErrorsTest {
    @Test fun workerAndBrainCodesAreThreePartSentences() {
        assertEquals("Brain refused VNode's token. Re-issue it on Brain and update VNode.", InboxRules.codeMessage("brain_http_401"))
        assertEquals("Brain refused VNode's token. Re-issue it on Brain and update VNode.", InboxRules.codeMessage("brain_http_403"))
        assertEquals("Brain's login page is blocking VNode. Add the path to the Cloudflare Access bypass.", InboxRules.codeMessage("access_blocked"))
        val phrases = mapOf(
            "name_conflict" to "Rename the file", "write_failed" to "Check Brain's disk", "bad_payload" to "send it again",
            "brain_http_500" to "Integrations page", "brain_http_502" to "Integrations page", "brain_http_422" to "send it again",
        )
        for ((c, phrase) in phrases) {
            val m = InboxRules.codeMessage(c)!!
            assertTrue("$c: $m", m.contains(phrase))
            assertTrue("$c: $m", m.length < 160)
            assertFalse(m.contains("Mac"))
        }
        assertNull(InboxRules.codeMessage("brain_http_"))
        assertNull(InboxRules.codeMessage("brain_http_abc"))
        assertNull(InboxRules.codeMessage("brain_http_5000"))
        assertEquals(
            "Brain had a problem. It retries on its own; if it stays, check Brain's Integrations page.",
            InboxRules.codeMessage("brain_http_500"),
        )
        assertNull(InboxRules.codeMessage("something_new"))
        assertNull(InboxRules.codeMessage(null))
    }

    @Test fun errorMessageUsesCodeThenHttp() {
        assertEquals(InboxRules.codeMessage("access_blocked"), InboxRules.errorMessage(409, "access_blocked"))
        assertEquals("Phone not paired", InboxRules.errorMessage(401, "unknown_thing"))
        assertTrue(InboxRules.errorMessage(500, null).startsWith("VNode had a problem"))
        assertTrue(InboxRules.errorMessage(500, null).contains("HTTP 500"))
        assertTrue(InboxRules.errorMessage(null, null).contains("HTTP ?"))
    }

    private fun failed(code: String?, msg: String?) =
        InboxJob("j1", "text", "", "failed", "t", 1, null, code, msg, false)

    @Test fun failedJobDetailKeepsFriendlyKnownCodes() {
        assertEquals("VNode queue is full, try later", InboxUi.jobDetail(failed("queue_full", null)))
        assertEquals(InboxRules.errorMessage(null, "too_large"), InboxUi.jobDetail(failed("too_large", "x")))
        assertEquals(InboxRules.errorMessage(null, "disk_reserve"), InboxUi.jobDetail(failed("disk_reserve", null)))
        assertEquals(InboxRules.errorMessage(null, "rate_limited"), InboxUi.jobDetail(failed("rate_limited", null)))
        assertTrue(InboxUi.jobDetail(failed("odd", "  "))!!.contains("Integrations"))
    }

    @Test fun failedJobDetailNeverFallsBackToBareNotDelivered() {
        assertEquals(InboxRules.codeMessage("write_failed"), InboxUi.jobDetail(failed("write_failed", "disk")))
        assertEquals("some worker words", InboxUi.jobDetail(failed("odd_code", "some worker words")))
        val none = InboxUi.jobDetail(failed(null, null))!!
        assertFalse(none.startsWith("Not delivered ("))
        assertTrue(none.contains("Integrations"))
    }

    @Test fun completedJobShowsWhereItWent() {
        fun done(kind: String, ref: String?) = InboxJob("j", kind, "", "completed", "t", 1, ref, null, null, false)
        assertEquals("In Brain · note abc123. Not necessarily processed yet.", InboxUi.jobDetail(done("text", "abc123")))
        assertEquals("In Brain · note abc123. Not necessarily processed yet.", InboxUi.jobDetail(done("url", "abc123")))
        assertEquals("In Brain · file 2026-01-01 vnode-x.md. Not necessarily processed yet.", InboxUi.jobDetail(done("md", "2026-01-01 vnode-x.md")))
        assertEquals("In Brain's inbox. Not necessarily processed yet.", InboxUi.jobDetail(done("text", null)))
    }
}

class InboxAuditWordingTest {
    @Test fun noMacWording() {
        val b = BrainStatus.parse(JSONObject("""{"snapshot":{"reachable":true,"mode":"dry_run"},"stale":false,"worker_stale":true,"queue":{}}"""))
        assertEquals("Delivery worker not reporting", InboxRules.brainHeadline(b))
        assertEquals("Delivery worker in dry run — nothing is delivered", InboxRules.dryRunNotice(b))
        assertEquals("Reported by delivery worker", InboxRules.REPORTED_BY)
        assertEquals("Delivery worker last seen", InboxRules.WORKER_SEEN_LABEL)
        assertEquals("Brain couldn't file", InboxRules.FAILED_IN_BRAIN_LABEL)
    }

    private fun brain(stale: Boolean = false, workerStale: Boolean = false, reachable: Boolean? = true) = BrainStatus.parse(
        JSONObject("""{"snapshot":{${if (reachable != null) "\"reachable\":$reachable" else ""}},"stale":$stale,"worker_stale":$workerStale,"queue":{}}"""),
    )
    private fun counts(q: Int) = InboxCounts(q, 0, 0, 0, 0, 0, 0)

    @Test fun waitingLineOnlyWhenQueuedAndBrainUnreachable() {
        val msg = "3 waiting: VNode can't reach Brain right now. They send automatically when it's back."
        assertEquals(msg, InboxRules.waitingNotice(counts(3), brain(stale = true)))
        assertEquals(msg, InboxRules.waitingNotice(counts(3), brain(workerStale = true)))
        assertEquals(msg, InboxRules.waitingNotice(counts(3), brain(reachable = false)))
        assertEquals("1 waiting: VNode can't reach Brain right now. It sends automatically when it's back.", InboxRules.waitingNotice(counts(1), brain(stale = true)))
        assertNull(InboxRules.waitingNotice(counts(0), brain(stale = true)))
        assertNull(InboxRules.waitingNotice(counts(3), brain()))
        assertNull(InboxRules.waitingNotice(null, brain(stale = true)))
        assertNull(InboxRules.waitingNotice(counts(3), null))
    }
}

class InboxAuditShareTest {
    private fun act(paired: Boolean = true, wifi: Boolean = true, sending: Boolean = false, file: Boolean = false, cut: Boolean = false) =
        InboxRules.shareAction(paired, wifi, sending, file, cut)

    @Test fun onlyPlainUncutTextAutoSends() {
        assertEquals(InboxRules.ShareAction.SEND_NOW, act())
        assertEquals(InboxRules.ShareAction.DRAFT_REVIEW, act(file = true))
        assertEquals(InboxRules.ShareAction.DRAFT_REVIEW, act(cut = true))
        assertEquals(InboxRules.ShareAction.DRAFT_REVIEW, act(sending = true)) // a send is already in flight
        assertEquals(InboxRules.ShareAction.DRAFT_UNPAIRED, act(paired = false))
        assertEquals(InboxRules.ShareAction.DRAFT_UNPAIRED, act(paired = false, file = true))
        assertEquals(InboxRules.ShareAction.DRAFT_NO_WIFI, act(wifi = false))
        assertEquals("Saved as draft. Review and tap Send.", InboxRules.REVIEW_NOTICE)
        assertEquals("Sent to VNode. It goes to Brain in about a minute.", InboxRules.SENT_NOTICE)
        assertEquals(35_000L, InboxRules.AUTO_REFRESH_MS)
    }

    @Test fun onlyContentUrisFromOtherAppsAreRead() {
        val me = "com.designinnsaeit.vhome.watch"
        assertTrue(InboxRules.shareUriOk("content", "com.android.providers.downloads.documents", me))
        assertTrue(InboxRules.shareUriOk("CONTENT", "media", me))
        assertFalse(InboxRules.shareUriOk("file", null, me))
        assertFalse(InboxRules.shareUriOk("file", "", me))
        assertFalse(InboxRules.shareUriOk(null, null, me))
        assertFalse(InboxRules.shareUriOk("http", "example.com", me))
        assertFalse(InboxRules.shareUriOk("content", me, me))
        assertFalse(InboxRules.shareUriOk("content", "$me.fileprovider", me))
        assertFalse(InboxRules.shareUriOk("content", null, me))
        assertTrue(InboxRules.shareUriOk("content", "${me}x", me)) // a different package that merely shares a prefix
    }

    @Test fun fileDraftNeverEvictsOthers() {
        fun d(i: Int, n: Int) = Draft(InboxRules.newKey(UUID.nameUUIDFromBytes(byteArrayOf(i.toByte()))), "a".repeat(n), "text", i.toLong())
        assertTrue(DraftStore.fits(emptyList(), 256 * 1024))
        assertTrue(DraftStore.fits(listOf(d(1, 700 * 1024)), 256 * 1024))
        assertFalse(DraftStore.fits(listOf(d(1, 800 * 1024)), 256 * 1024))
        assertFalse(DraftStore.fits((1..20).map { d(it, 1) }, 10))
        assertEquals(1024 * 1024, InboxRules.MAX_DRAFT_BYTES)
    }

    @Test fun decodeStripsBom() {
        assertEquals("hi", InboxRules.decodeText(byteArrayOf(0xEF.toByte(), 0xBB.toByte(), 0xBF.toByte(), 0x68, 0x69)))
    }

    @Test fun labelNeedsSomethingAlphanumericAndNoLeadingDots() {
        assertEquals("hidden.md", InboxRules.headerLabel("..hidden.md"))
        assertEquals("", InboxRules.headerLabel("..."))
        assertEquals("", InboxRules.headerLabel(" . _- "))
        assertEquals("a.md", InboxRules.headerLabel(".a.md"))
    }

    @Test fun pluralIsRight() {
        assertEquals("1 oldest draft was dropped", InboxRules.droppedText(1))
        assertEquals("3 oldest drafts were dropped", InboxRules.droppedText(3))
    }

    @Test fun fileKindFromNameThenMime() {
        assertEquals("md", InboxRules.fileKind("notes.md", "text/plain"))
        assertEquals("md", InboxRules.fileKind("NOTES.MARKDOWN", null))
        assertEquals("md", InboxRules.fileKind(null, "text/markdown"))
        assertEquals("md", InboxRules.fileKind(null, "text/x-markdown"))
        assertEquals("txt", InboxRules.fileKind("log.txt", "text/plain"))
        assertEquals("txt", InboxRules.fileKind(null, "text/csv"))
        assertEquals("txt", InboxRules.fileKind("readme", null))
    }

    @Test fun headerLabelIsAsciiAndShort() {
        assertEquals("notes 1.md", InboxRules.headerLabel("notes 1.md"))
        assertEquals("cafe.md", InboxRules.headerLabel("café.md"))
        assertEquals("abcd.md", InboxRules.headerLabel("a/b\\c\nd.md"))
        assertEquals("", InboxRules.headerLabel(null))
        assertEquals("", InboxRules.headerLabel("日本語"))
        assertEquals(40, InboxRules.headerLabel("a".repeat(100)).length)
    }

    @Test fun readCappedStopsAtLimit() {
        assertEquals(5, InboxRules.readCapped(ByteArrayInputStream("hello".toByteArray()), 10)!!.size)
        assertEquals(10, InboxRules.readCapped(ByteArrayInputStream(ByteArray(10)), 10)!!.size)
        assertNull(InboxRules.readCapped(ByteArrayInputStream(ByteArray(11)), 10))
        assertEquals(262144, InboxRules.MAX_FILE_BYTES)
    }

    @Test fun decodeTextIsStrictUtf8() {
        assertEquals("héllo", InboxRules.decodeText("héllo".toByteArray(Charsets.UTF_8)))
        assertNull(InboxRules.decodeText(byteArrayOf(0x68, 0xFF.toByte(), 0x69)))
        assertNull(InboxRules.decodeText(byteArrayOf(0x68, 0x00, 0x69)))
    }

    @Test fun counterUsesTheCapOfTheKind() {
        assertEquals("5 / 8192 bytes", InboxRules.counter("hello"))
        assertEquals("5 / 262144 bytes", InboxRules.counter("hello", "md"))
        assertEquals("5 / 262144 bytes", InboxRules.counter("hello", "txt"))
    }
}

class InboxAuditDraftTest {
    @Test fun fileDraftKeepsKindAndLabelAcrossReload() {
        val f = File.createTempFile("drafts", ".json").apply { delete(); deleteOnExit() }
        val a = DraftStore(f).add("# hi", kind = "md", label = "notes.md")
        assertEquals("md", a.draft.kind); assertEquals("notes.md", a.draft.label)
        val again = DraftStore(f).all().single()
        assertEquals("md", again.kind); assertEquals("notes.md", again.label)
        assertEquals("text", DraftStore(f).add("plain").draft.kind)
        assertEquals("", DraftStore(f).add("plain2").draft.label)
    }
}
