package com.designinnsaeit.vhome.watch

import android.content.Context
import android.graphics.Typeface
import android.text.InputType
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView

/** Wording that needs no Android, kept apart so it can be unit tested. */
object InboxUi {
    fun preview(text: String, max: Int = 80): String {
        val one = text.trim().replace(Regex("\\s+"), " ")
        return if (one.length <= max) one else one.take(max - 1) + "…"
    }

    fun jobTitle(j: InboxJob): String = j.label.ifEmpty { "${j.kind} ${j.id.take(8)}" }

    fun draftTitle(d: Draft): String = d.label.ifEmpty { preview(d.text) }

    fun jobDetail(j: InboxJob): String? = when {
        j.status == "failed" -> InboxRules.codeMessage(j.errorCode) ?: j.errorMsg
            ?: "Brain couldn't take this item. Check Brain's Integrations page."
        j.status == "completed" ->
            (j.resultRef?.let { "In Brain · ${if (InboxRules.isFileKind(j.kind)) "file" else "note"} $it" } ?: "In Brain's inbox") +
                ". Not necessarily processed yet."
        else -> null
    }

    fun jobDescription(j: InboxJob): String = "${jobTitle(j)}, ${InboxRules.statusLabel(j.status)}"

    fun queueSummary(c: InboxCounts): String =
        "Queued ${c.queued} · Sending ${c.claimed + c.processing} · Accepted ${c.completed} · Failed ${c.failed} · Cancelled ${c.cancelled}" +
            if (c.unknown > 0) " · Unknown ${c.unknown}" else ""
}

/** Programmatic views in the app's existing styles (themes.xml); tap targets are at least 48 dp. */
class InboxViews(val ctx: Context) {
    private val d = ctx.resources.displayMetrics.density
    fun dp(v: Int) = (v * d).toInt()

    fun text(style: Int, s: CharSequence = "", bold: Boolean = false): TextView = TextView(ctx, null, 0, style).apply {
        text = s
        if (bold) setTypeface(typeface, Typeface.BOLD)
    }

    fun body(s: CharSequence = "") = text(R.style.T_Body, s)
    fun dim(s: CharSequence = "") = text(R.style.T_Dim, s)
    fun label(s: CharSequence) = text(R.style.T_Label, s)

    fun button(s: CharSequence, style: Int = R.style.Btn_Ghost, onClick: () -> Unit): Button =
        Button(ctx, null, 0, style).apply {
            text = s
            minHeight = dp(48)
            setOnClickListener { onClick() }
        }

    fun field(hint: String): EditText = EditText(ctx, null, 0, R.style.Field).apply {
        this.hint = hint
        isSingleLine = false
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_MULTI_LINE or InputType.TYPE_TEXT_FLAG_CAP_SENTENCES
        minLines = 4
        gravity = Gravity.TOP or Gravity.START
    }

    fun vbox(): LinearLayout = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }

    fun lp(top: Int = 0, width: Int = ViewGroup.LayoutParams.MATCH_PARENT) =
        LinearLayout.LayoutParams(width, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(top) }

    fun rule(): View = View(ctx).apply {
        setBackgroundColor(ctx.getColor(R.color.ink))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(3))
    }

    fun hairline(): View = View(ctx).apply {
        setBackgroundColor(ctx.getColor(R.color.grey))
        layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 1)
    }

    /** A status line led by a square mark. Colour is never the only signal: the label always says it too. */
    fun statusLine(label: String, mark: Int, colour: Int): TextView = text(R.style.T_Small, label, bold = true).apply {
        setTextColor(ctx.getColor(colour))
        compoundDrawablePadding = dp(8)
        setCompoundDrawablesRelativeWithIntrinsicBounds(mark, 0, 0, 0)
        gravity = Gravity.CENTER_VERTICAL
        minHeight = dp(24)
    }

    fun markFor(level: HealthLevel, stale: Boolean): Int = when {
        stale -> R.drawable.sq_info
        level == HealthLevel.ERROR -> R.drawable.sq_bad
        level == HealthLevel.WARN -> R.drawable.sq_guided
        level == HealthLevel.OK -> R.drawable.sq_ok
        else -> R.drawable.sq_info
    }

    fun colourFor(c: NodeHealthUi.Colour): Int = when (c) {
        NodeHealthUi.Colour.NORMAL -> R.color.ink
        NodeHealthUi.Colour.RED -> R.color.red
        NodeHealthUi.Colour.AMBER -> R.color.warn_text
        NodeHealthUi.Colour.GREY -> R.color.text_dim
    }

    fun markForTone(t: InboxRules.Tone): Int = when (t) {
        InboxRules.Tone.GOOD -> R.drawable.sq_ok
        InboxRules.Tone.WAIT -> R.drawable.sq_guided
        InboxRules.Tone.BAD -> R.drawable.sq_bad
        InboxRules.Tone.QUIET -> R.drawable.sq_info
    }

    fun colourForTone(t: InboxRules.Tone): Int = when (t) {
        InboxRules.Tone.GOOD -> R.color.ok_green
        InboxRules.Tone.WAIT -> R.color.warn_text
        InboxRules.Tone.BAD -> R.color.red
        InboxRules.Tone.QUIET -> R.color.text_dim
    }
}
