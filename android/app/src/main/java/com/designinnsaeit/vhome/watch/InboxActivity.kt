package com.designinnsaeit.vhome.watch

import android.app.Activity
import android.content.Intent
import android.graphics.Typeface
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.io.File
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import okhttp3.Dns

/**
 * Send text or a link to VNode's inbox, and see Brain status. Refreshes on resume and by the Refresh button only;
 * nothing runs in the background. "Accepted by Brain" means Brain's inbox took it, never that it was processed.
 */
class InboxActivity : Activity() {
    private companion object {
        // Shares are saved here, not in the activity scope, so a rotation or back press cannot lose one mid-read.
        val shareScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }

    private val scope = CoroutineScope(Dispatchers.Main + SupervisorJob())
    private lateinit var store: NodeStore
    private lateinit var drafts: DraftStore
    private lateinit var ui: InboxViews
    private lateinit var tabInbox: Button
    private lateinit var tabBrain: Button
    private lateinit var notice: TextView
    private lateinit var body: LinearLayout
    private lateinit var composeBox: LinearLayout
    private lateinit var field: EditText
    private lateinit var counter: TextView
    private lateinit var sendBtn: Button

    private var tab = 0
    private var sending = false // a submit / cancel / retry is in flight
    private var refreshing = false
    private var pendingRefresh = false
    private val busy get() = sending || refreshing
    private var composeText = ""
    private var listError: String? = null
    private var jobs: List<InboxJob> = emptyList()
    private var counts: InboxCounts? = null
    private var unreadable = 0
    private var listAt: Long? = null
    private var brainAt: Long? = null
    private var brain: BrainStatus? = null
    private var brainError: String? = null
    private var loaded = false
    private var sendResult: Pair<Boolean, String>? = null
    private var cachedClient: InboxClient? = null
    private var autoRefresh: Job? = null

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        EventLog.installCrashHandler(this)
        store = NodeStore(this)
        drafts = DraftStore(File(filesDir, "inbox_drafts.json"))
        ui = InboxViews(this)
        buildShell()
        // The Bundle never carries more than the 8 KB cap (see onSaveInstanceState), but cut on the way back in too.
        setCompose(InboxRules.truncateUtf8(savedInstanceState?.getString("compose").orEmpty()).first)
        if (savedInstanceState == null && intent.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY == 0) handleShare(intent)
        render()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        handleShare(intent)
        render()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        // ponytail: text typed past 8 KB is not restored after a rotation; it could not be sent anyway.
        outState.putString("compose", InboxRules.truncateUtf8(composeText).first)
    }

    override fun onResume() {
        super.onResume()
        refresh()
    }

    override fun onStop() {
        autoRefresh?.cancel(); pendingRefresh = false // resume refreshes anyway
        super.onStop()
    }

    override fun onDestroy() {
        scope.cancel()
        super.onDestroy()
    }

    // ---- Shell -------------------------------------------------------------------------------------

    private fun buildShell() {
        val root = ui.vbox()
        root.addView(ui.label("Inbox").apply { setPadding(ui.dp(20), ui.dp(24), ui.dp(20), ui.dp(20)) }, ui.lp())
        root.addView(ui.rule())
        val tabs = LinearLayout(this)
        tabInbox = ui.button("Inbox", R.style.Btn_Text) { tab = 0; render() }
        tabBrain = ui.button("Brain status", R.style.Btn_Text) { tab = 1; render() }
        tabs.addView(tabInbox, LinearLayout.LayoutParams(0, ui.dp(48), 1f))
        tabs.addView(tabBrain, LinearLayout.LayoutParams(0, ui.dp(48), 1f))
        root.addView(tabs, ui.lp())
        root.addView(ui.rule())
        notice = ui.body().apply {
            setBackgroundColor(getColor(R.color.yellow)); setPadding(ui.dp(20), ui.dp(14), ui.dp(20), ui.dp(14))
            visibility = View.GONE; accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE
        }
        root.addView(notice, ui.lp())
        composeBox = ui.vbox().apply { setPadding(ui.dp(20), ui.dp(20), ui.dp(20), 0) }
        buildCompose()
        root.addView(composeBox, ui.lp())
        body = ui.vbox().apply { setPadding(ui.dp(20), 0, ui.dp(20), ui.dp(40)) }
        root.addView(body, ui.lp())
        setContentView(ScrollView(this).apply {
            setBackgroundColor(getColor(R.color.paper)); fitsSystemWindows = true; isFillViewport = true
            addView(root)
        })
    }

    private fun setNotice(s: String?) {
        notice.visibility = if (s == null) View.GONE else View.VISIBLE
        if (s != null) notice.text = s
    }

    // ---- Share target ------------------------------------------------------------------------------

    private fun handleShare(i: Intent?) {
        if (i?.action != Intent.ACTION_SEND || i.type?.startsWith("text/") != true) return
        if (i.flags and Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY != 0) return // re-delivered from Recents, not a new share
        val raw: String?
        val stream: Uri?
        try {
            raw = i.getCharSequenceExtra(Intent.EXTRA_TEXT)?.toString()
            @Suppress("DEPRECATION")
            stream = i.getParcelableExtra<Uri>(Intent.EXTRA_STREAM)
        } catch (e: RuntimeException) { // BadParcelableException and friends: a hostile or broken sender
            setIntent(Intent()); EventLog.add(this, "inbox share: unreadable extras"); setNotice("Couldn't read what was shared. Nothing was saved."); return
        }
        if (stream == null && raw.isNullOrBlank()) return
        setIntent(Intent()) // handled: a rotation must not save it twice
        if (stream != null) {
            if (InboxRules.shareUriOk(stream.scheme, stream.authority, packageName)) { shareFile(stream, i.type, raw); return }
            EventLog.add(this, "inbox share: refused a ${stream.scheme} uri")
            if (raw.isNullOrBlank()) { setNotice("Couldn't open that file. Nothing was saved."); return }
        }
        shareText(raw!!)
    }

    private fun shareText(raw: String) {
        val (text, cut) = InboxRules.truncateUtf8(raw)
        val notes = mutableListOf<String>()
        if (cut) notes += "Shared text was cut to 8 KB"
        val app = this
        shareScope.launch { app.saveShared(text, InboxRules.detectKind(text), "", isFile = false, cut = cut, notes = notes) }
    }

    private class SharedFile(val name: String?, val bytes: ByteArray?, val unreadable: Boolean)

    /**
     * A shared .md/.txt file. Read and saved in shareScope, which outlives the activity, so a rotation during the read
     * cannot lose it: the draft is saved and shows in the list even if this screen is gone.
     */
    private fun shareFile(uri: Uri, mime: String?, fallbackText: String?) {
        val resolver = contentResolver
        val app = this
        shareScope.launch {
            val f = try {
                val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
                    if (it.moveToFirst()) it.getString(0) else null
                }
                val input = resolver.openInputStream(uri)
                if (input == null) SharedFile(name, null, true) else SharedFile(name, input.use { InboxRules.readCapped(it) }, false)
            } catch (e: Exception) { // SecurityException, FileNotFoundException, IOException, provider crashes
                SharedFile(null, null, true)
            }
            val text = f.bytes?.let { InboxRules.decodeText(it) }
            if (text != null && text.isNotBlank()) {
                app.saveShared(text, InboxRules.fileKind(f.name, mime), InboxRules.headerLabel(f.name), isFile = true, cut = false, notes = mutableListOf())
            } else if (!fallbackText.isNullOrBlank()) { // an app that sends both a file and text: keep the text
                val (t, cut) = InboxRules.truncateUtf8(fallbackText)
                app.saveShared(t, InboxRules.detectKind(t), "", isFile = false, cut = cut, notes = if (cut) mutableListOf("Shared text was cut to 8 KB") else mutableListOf())
            } else {
                val why = when {
                    f.unreadable -> "Couldn't open the shared file. Nothing was saved."
                    f.bytes == null -> "That file is over 256 KB, so it wasn't saved."
                    text == null -> "Couldn't read that file as text. Nothing was saved."
                    else -> "That file is empty. Nothing was saved."
                }
                withContext(Dispatchers.Main) {
                    EventLog.add(app, "inbox share: $why")
                    if (!app.isDestroyed) app.setNotice(why)
                }
            }
        }
    }

    /** Saves the share as a draft first (so its key exists), then sends it only if [InboxRules.shareAction] says so. */
    private suspend fun saveShared(text: String, kind: String, label: String, isFile: Boolean, cut: Boolean, notes: MutableList<String>) {
        val added = withContext(Dispatchers.IO) {
            if (isFile && !DraftStore.fits(drafts.all(), InboxRules.bytes(text))) null // never evict other drafts for a file
            else drafts.add(text, kind = kind, label = label)
        }
        withContext(Dispatchers.Main) {
            if (isDestroyed) return@withContext // the draft is saved and shows in the list next time
            if (added == null) { setNotice("Too many drafts to add this file. Send or delete a draft first."); render(); return@withContext }
            if (!added.saved) notes += "Couldn't save draft"
            if (added.dropped > 0) notes += InboxRules.droppedText(added.dropped)
            // Decided here, on the main thread, from the real send state: a running refresh does not matter.
            when (InboxRules.shareAction(store.isPaired(), HomeNetwork.wifiNetwork(this@InboxActivity) != null, sending, isFile, cut)) {
                InboxRules.ShareAction.SEND_NOW -> { setNotice(notes.joinToString(". ").ifEmpty { null }); sendDraft(added.draft); return@withContext }
                InboxRules.ShareAction.DRAFT_UNPAIRED -> notes += "Phone not paired — saved as draft"
                InboxRules.ShareAction.DRAFT_NO_WIFI -> notes += "Not on home Wi-Fi — saved as draft"
                InboxRules.ShareAction.DRAFT_REVIEW -> notes += InboxRules.REVIEW_NOTICE
            }
            setNotice(notes.joinToString(". ").ifEmpty { null }) // empty string would show a blank amber bar
            render()
        }
    }

    // ---- Data --------------------------------------------------------------------------------------

    // Built once per activity; the token/keystore read happens off the main thread. A failed build is not cached.
    private suspend fun client(): InboxClient {
        cachedClient?.let { return it }
        return withContext(Dispatchers.IO) {
            val host = store.host; val id = store.nodeId; val token = store.token()
            if (host == null || id == null || token == null) throw InboxException("Phone not paired")
            val net = HomeNetwork.wifiNetwork(this@InboxActivity) ?: throw InboxException("Not on home Wi-Fi")
            val dns = object : Dns {
                override fun lookup(hostname: String): List<java.net.InetAddress> =
                    runCatching { net.getAllByName(hostname).toList() }.getOrElse { Dns.SYSTEM.lookup(hostname) }
            }
            InboxClient(NodeClient(host, id, false, net.socketFactory, token, dns = dns))
        }.also { cachedClient = it }
    }

    private fun refresh() {
        if (refreshing || sending) { pendingRefresh = true; return } // runs once the current work is done
        pendingRefresh = false
        refreshing = true; syncState()
        scope.launch {
            try {
                val c = client()
                try { c.list().let { jobs = it.jobs; counts = it.counts; unreadable = it.unreadable; listAt = System.currentTimeMillis(); listError = null } } catch (e: InboxException) { listError = e.message; EventLog.add(this@InboxActivity, "inbox refresh (list) failed: ${e.message}") }
                try { brain = c.brainStatus(); brainAt = System.currentTimeMillis(); brainError = null } catch (e: InboxException) { brainError = e.message; EventLog.add(this@InboxActivity, "inbox refresh (brain status) failed: ${e.message}") }
            } catch (e: InboxException) {
                listError = e.message; brainError = e.message
                EventLog.add(this@InboxActivity, "inbox refresh failed: ${e.message}")
            }
            loaded = true
            refreshing = false; syncState()
            if (pendingRefresh) refresh()
        }
    }

    /** One refresh about 35 s after a send, when the delivery worker has had time to pick the job up. */
    private fun scheduleRefresh() {
        autoRefresh?.cancel()
        autoRefresh = scope.launch { delay(InboxRules.AUTO_REFRESH_MS); refresh() } // refresh() queues itself if busy
    }

    private fun syncState() { syncCompose(); render() }

    private fun sendDraft(d: Draft) {
        if (sending) return
        sending = true; syncState()
        doSend(d)
    }

    /** [sending] is already true. */
    private fun doSend(d: Draft) {
        scope.launch {
            // NonCancellable: once the POST is confirmed Sent, the draft must go even if the screen is closing.
            val out = withContext(NonCancellable) {
                val o = try {
                    client().submit(d.key, d.text, d.kind, d.label)
                } catch (e: InboxException) {
                    SubmitOutcome.NotDelivered((e.message ?: "Not delivered") + ". Saved as draft")
                }
                if (o is SubmitOutcome.Sent) withContext(Dispatchers.IO) { drafts.remove(d.key) }
                o
            }
            when (out) {
                is SubmitOutcome.Sent -> { sendResult = true to InboxRules.SENT_NOTICE; scheduleRefresh() }
                is SubmitOutcome.NotDelivered -> {
                    sendResult = false to out.message
                    EventLog.add(this@InboxActivity, "inbox submit failed (${d.kind}, ${InboxRules.bytes(d.text)} B): ${out.message}")
                }
            }
            sending = false
            refresh()
        }
    }

    private fun act(j: InboxJob, cancel: Boolean) {
        if (busy) return
        sending = true; syncState()
        scope.launch {
            try {
                val c = client()
                if (cancel) c.cancel(j.id) else c.retry(j.id)
                sendResult = true to if (cancel) "Cancelled" else "Queued again"
            } catch (e: InboxException) {
                sendResult = false to (e.message ?: "Failed")
                EventLog.add(this@InboxActivity, "inbox ${if (cancel) "cancel" else "retry"} failed: ${e.message}")
            }
            sending = false
            refresh()
        }
    }

    private fun sendCompose() {
        when (InboxRules.check(composeText)) {
            InboxRules.Check.EMPTY -> return
            InboxRules.Check.TOO_LARGE -> { sendResult = false to InboxRules.errorMessage(null, "too_large"); render(); return }
            InboxRules.Check.OK -> {}
        }
        if (sending) return
        sending = true; syncState()
        val text = composeText
        scope.launch {
            // The draft (and its key) exists before the first attempt, so every resend reuses the same key.
            val a = withContext(NonCancellable + Dispatchers.IO) {
                drafts.add(text).also { if (!it.saved) drafts.remove(it.draft.key) }
            }
            if (!a.saved) { sending = false; syncState(); setNotice("Couldn't save draft"); return@launch } // keep the text on screen; nothing was sent
            setCompose("")
            if (a.dropped > 0) setNotice("${InboxRules.droppedText(a.dropped)} (limit ${InboxRules.MAX_DRAFTS}).")
            doSend(a.draft)
        }
    }

    // ---- Render ------------------------------------------------------------------------------------

    private fun render() {
        if (!::body.isInitialized) return
        listOf(tabInbox to 0, tabBrain to 1).forEach { (b, i) ->
            b.setTypeface(null, if (tab == i) Typeface.BOLD else Typeface.NORMAL)
            b.setTextColor(getColor(if (tab == i) R.color.ink else R.color.text_dim))
            b.contentDescription = b.text.toString() + if (tab == i) ", selected" else ""
            b.isSelected = tab == i
        }
        composeBox.visibility = if (tab == 0) View.VISIBLE else View.GONE
        body.removeAllViews()
        if (tab == 0) renderInbox() else renderBrain()
    }

    // The compose field lives outside `body`, so render() never recreates it (text, focus and cursor survive).
    private fun buildCompose() {
        composeBox.addView(ui.text(R.style.T_Small, "New item"))
        field = ui.field("Text or a link to send to VNode")
        counter = ui.dim()
        sendBtn = ui.button("Send", R.style.Btn_NodePrimary) { sendCompose() }
        field.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun onTextChanged(s: CharSequence?, a: Int, b: Int, c: Int) {}
            override fun afterTextChanged(s: Editable?) { composeText = s.toString(); syncCompose() }
        })
        composeBox.addView(field, ui.lp(8))
        composeBox.addView(counter, ui.lp(6))
        composeBox.addView(sendBtn, ui.lp(12, width = ViewGroup.LayoutParams.WRAP_CONTENT))
    }

    private fun setCompose(t: String) {
        composeText = t
        if (field.text.toString() != t) field.setText(t).also { field.setSelection(field.text.length) }
        syncCompose()
    }

    private fun syncCompose() {
        val over = InboxRules.check(composeText) == InboxRules.Check.TOO_LARGE
        counter.text = InboxRules.counter(composeText) +
            if (over) ". Too long" else if (composeText.isNotBlank()) ". Sends as ${InboxRules.detectKind(composeText)}" else ""
        counter.setTextColor(getColor(if (over) R.color.red else R.color.text_dim))
        sendBtn.isEnabled = !busy && InboxRules.check(composeText) == InboxRules.Check.OK
        sendBtn.alpha = if (sendBtn.isEnabled) 1f else 0.4f
    }

    private fun refreshButton() = ui.button(if (busy) "Refreshing…" else "Refresh") { refresh() }.also { it.isEnabled = !busy }

    private fun clock(t: Long) = java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault()).format(java.util.Date(t))

    private fun heading(s: String) = ui.label(s).also { it.setPadding(0, ui.dp(28), 0, ui.dp(4)) }

    private fun renderInbox() {
        sendResult?.let { (ok, msg) ->
            body.addView(
                ui.statusLine(msg, if (ok) R.drawable.sq_ok else R.drawable.sq_bad, if (ok) R.color.ok_green else R.color.red)
                    .apply { accessibilityLiveRegion = View.ACCESSIBILITY_LIVE_REGION_POLITE },
                ui.lp(12),
            )
        }

        InboxRules.waitingNotice(counts, brain)?.let { body.addView(ui.statusLine(it, R.drawable.sq_guided, R.color.warn_text), ui.lp(12)) }

        val ds = drafts.all().reversed()
        if (ds.isNotEmpty()) {
            body.addView(heading("Drafts, not delivered"), ui.lp())
            ds.forEach { body.addView(draftRow(it)) }
        }

        body.addView(heading("Recent"), ui.lp())
        body.addView(refreshButton(), ui.lp(4, width = ViewGroup.LayoutParams.WRAP_CONTENT))
        val err = listError
        if (err != null) body.addView(ui.statusLine(err, R.drawable.sq_bad, R.color.red), ui.lp(8))
        val cached = ui.vbox().also { if (err != null) it.alpha = 0.5f } // old data from before a failed refresh is greyed
        if (err != null && listAt != null) cached.addView(ui.dim("Last updated ${clock(listAt!!)}"), ui.lp(8))
        if (counts != null) cached.addView(ui.dim(InboxUi.queueSummary(counts!!)), ui.lp(8))
        else if (loaded && err == null) cached.addView(ui.dim("Queue counts unavailable"), ui.lp(8))
        if (unreadable > 0) cached.addView(ui.dim("$unreadable item${if (unreadable == 1) "" else "s"} couldn't be read"), ui.lp(8))
        if (err == null && loaded && jobs.isEmpty() && unreadable == 0) cached.addView(ui.dim("Nothing sent yet."), ui.lp(8))
        jobs.forEach { cached.addView(jobRow(it)) }
        body.addView(cached)
    }

    private fun draftRow(d: Draft): View = ui.vbox().apply {
        setPadding(0, ui.dp(12), 0, ui.dp(12))
        addView(ui.hairline())
        addView(ui.body(InboxUi.draftTitle(d)), ui.lp(10))
        addView(ui.dim("${d.kind} · ${InboxRules.counter(d.text, d.kind)}"))
        val row = LinearLayout(context)
        val what = InboxUi.preview(d.text, 30)
        row.addView(ui.button("Send") { sendDraft(d) }.also { it.isEnabled = !busy; it.contentDescription = "Send draft: $what" })
        row.addView(ui.button("Delete", R.style.Btn_Text) { scope.launch { withContext(Dispatchers.IO) { drafts.remove(d.key) }; render() } }.also { it.contentDescription = "Delete draft: $what" })
        addView(row, ui.lp(8))
    }

    private fun jobRow(j: InboxJob): View = ui.vbox().apply {
        setPadding(0, ui.dp(12), 0, ui.dp(12))
        contentDescription = InboxUi.jobDescription(j)
        addView(ui.hairline())
        val tone = InboxRules.statusTone(j.status)
        addView(ui.statusLine(InboxRules.statusLabel(j.status), ui.markForTone(tone), ui.colourForTone(tone)), ui.lp(10))
        addView(ui.body(InboxUi.jobTitle(j)), ui.lp(2))
        InboxUi.jobDetail(j)?.let { addView(ui.dim(it)) }
        if (j.canCancel || j.canRetry) {
            val row = LinearLayout(context)
            val t = InboxUi.jobTitle(j)
            if (j.canCancel) row.addView(ui.button("Cancel") { act(j, true) }.also { it.isEnabled = !busy; it.contentDescription = "Cancel $t" })
            if (j.canRetry) row.addView(ui.button("Retry") { act(j, false) }.also { it.isEnabled = !busy; it.contentDescription = "Retry $t" })
            addView(row, ui.lp(8))
        }
    }

    private fun renderBrain() {
        body.addView(refreshButton(), ui.lp(0, width = ViewGroup.LayoutParams.WRAP_CONTENT))
        brainError?.let { body.addView(ui.statusLine(it, R.drawable.sq_bad, R.color.red), ui.lp(12)) }
        val b = brain
        if (b == null) {
            if (loaded && brainError == null) body.addView(ui.dim("No Brain status yet."), ui.lp(12))
            return
        }
        val out = ui.vbox().also { body.addView(it); if (brainError != null) it.alpha = 0.5f } // greyed when the refresh failed
        if (brainError != null && brainAt != null) out.addView(ui.dim("Last updated ${clock(brainAt!!)}"), ui.lp(8))
        val stale = InboxRules.brainStale(b)
        val level = InboxRules.brainLevel(b)
        val headline = InboxRules.brainHeadline(b)
        out.addView(
            ui.statusLine(headline, ui.markFor(level, stale), ui.colourFor(NodeHealthUi.colour(level, stale)))
                .apply { textSize = 22f },
            ui.lp(16),
        )
        InboxRules.authNotice(b)?.let { out.addView(ui.statusLine(it, R.drawable.sq_bad, R.color.red), ui.lp(8)) }
        InboxRules.dryRunNotice(b)?.let { out.addView(ui.statusLine(it, R.drawable.sq_guided, R.color.warn_text), ui.lp(8)) }
        out.addView(ui.dim(InboxRules.REPORTED_BY), ui.lp(4))
        fun row(k: String, v: String) {
            out.addView(ui.hairline(), ui.lp(12))
            val r = LinearLayout(this)
            r.setPadding(0, ui.dp(10), 0, ui.dp(10))
            r.addView(ui.body(k), LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f))
            r.addView(ui.body(v).apply { setTypeface(typeface, Typeface.BOLD) })
            r.contentDescription = "$k: $v"
            out.addView(r)
        }
        row(InboxRules.WORKER_SEEN_LABEL, InboxRules.ageText(b.workerSeenAgeS))
        row("Brain report", InboxRules.ageText(b.snapshotAgeS))
        b.reachable?.let { row("Brain reachable", if (it) "Yes" else "No") }
        b.heartbeat?.let { row("Heartbeat", it) }
        b.pending?.let { row("Pending", "$it") }
        b.processedToday?.let { row("Processed today", "$it") }
        b.needsReview?.let { row("Needs review", "$it") }
        b.failed?.let { row(InboxRules.FAILED_IN_BRAIN_LABEL, "$it") }
        out.addView(heading("VNode queue"), ui.lp())
        out.addView(ui.dim(b.queue?.let { InboxUi.queueSummary(it) } ?: "Queue counts unavailable"))
    }
}
