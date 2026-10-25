package com.designinnsaeit.vhome.watch

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.text.TextPaint
import android.text.TextUtils
import android.util.AttributeSet
import android.util.TypedValue
import android.view.View
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/** Pure rules behind the health dashboard: colours, gauge geometry, sparkline mapping, wording. No Android types. */
object Viz {
    /** Traffic light. INFO and anything stale are GREY: neutral, never green. */
    enum class Tone { OK, WARN, ERROR, GREY }

    // Same hues as colors.xml (ok_green, warn_text, red, text_dim); drawing code has no Context.
    val C_OK = 0xFF1E7B34.toInt()
    val C_WARN = 0xFF8A5A00.toInt()
    val C_ERROR = 0xFFD62828.toInt()
    val C_GREY = 0xFF808080.toInt()
    /** Text on paper / paper_2: red needs the darker shade to reach 4.5:1. */
    val T_ERROR = 0xFFC52525.toInt()
    val T_GREY = 0xFF5E5E5E.toInt()
    const val INK = 0xFF151515.toInt()
    const val TRACK = 0xFFE4E4DC.toInt()
    const val BORDER = 0xFFCFCFC8.toInt()

    fun toneOf(level: HealthLevel, stale: Boolean): Tone = when {
        stale -> Tone.GREY
        level == HealthLevel.OK -> Tone.OK
        level == HealthLevel.WARN -> Tone.WARN
        level == HealthLevel.ERROR -> Tone.ERROR
        else -> Tone.GREY
    }

    fun colour(t: Tone): Int = when (t) { Tone.OK -> C_OK; Tone.WARN -> C_WARN; Tone.ERROR -> C_ERROR; Tone.GREY -> C_GREY }
    fun textColour(t: Tone): Int = when (t) { Tone.OK -> C_OK; Tone.WARN -> C_WARN; Tone.ERROR -> T_ERROR; Tone.GREY -> T_GREY }

    /** The word that carries the level for people who don't see colour. */
    fun statusWord(level: HealthLevel, stale: Boolean): String = when {
        stale -> "No data"
        level == HealthLevel.OK -> "OK"
        level == HealthLevel.WARN -> "Check"
        level == HealthLevel.ERROR -> "Problem"
        else -> "Info"
    }

    // ---- gauge geometry -------------------------------------------------------------------------

    const val RING_START = 135f
    const val RING_SWEEP = 270f

    /** Where a value sits on the dial, 0..1. For Wi-Fi (higher is better) the dial still fills with a stronger signal. */
    fun fraction(value: Double, min: Double, max: Double): Float =
        if (max <= min) 0f else ((value - min) / (max - min)).coerceIn(0.0, 1.0).toFloat()

    fun fraction(m: HealthMetric): Float = fraction(m.value, m.min, m.max)

    /** Faint tick marks at the warn and error thresholds (same scale as the fill, whichever direction is worse). */
    fun tickFractions(m: HealthMetric): List<Float> =
        listOfNotNull(m.warn, m.error).filter { it in m.min..m.max }.map { fraction(it, m.min, m.max) }

    fun angleAt(f: Float): Float = RING_START + RING_SWEEP * f.coerceIn(0f, 1f)

    fun formatValue(v: Double): String =
        if (abs(v) >= 100 || abs(v - v.roundToInt()) < 0.05) v.roundToInt().toString() else String.format(Locale.US, "%.1f", v)

    fun spokenUnit(unit: String): String = when (unit) {
        "°C", "C" -> " degrees"
        "%" -> " percent"
        "MB" -> " megabytes"
        "MHz" -> " megahertz"
        "V" -> " volts"
        "dBm" -> " decibel milliwatts"
        "" -> ""
        else -> " $unit"
    }

    /** "Temperature 45 degrees, OK" — or "Temperature, no data" when stale. */
    fun gaugeDescription(label: String, m: HealthMetric?, level: HealthLevel, stale: Boolean, extra: String = ""): String {
        if (stale || m == null) return "$label, no data"
        val tail = if (extra.isEmpty()) "" else ", $extra"
        return "$label ${formatValue(m.value)}${spokenUnit(m.unit)}, ${statusWord(level, false)}$tail"
    }

    fun wifiDescription(m: HealthMetric?, bars: Int?, level: HealthLevel, stale: Boolean): String =
        if (stale || m == null) "Wi-Fi, no data"
        else "Wi-Fi signal ${if (bars != null) "$bars of 4 bars, " else ""}${formatValue(m.value)} decibel milliwatts, ${statusWord(level, false)}"

    fun donutDescription(c: RedirectCounts?, stale: Boolean): String =
        if (stale || c == null) "Redirects, no data" else "Redirects: ${c.ok} ok, ${c.failed} failed"

    /** Share of failed redirects, 0..1; 0 when nothing has been counted. */
    fun failedShare(ok: Int, failed: Int): Float = if (ok + failed <= 0) 0f else failed.toFloat() / (ok + failed)

    fun redirectsText(c: RedirectCounts): String = "${c.ok} ok · ${c.failed} failed"

    // ---- plain-word tiles ----------------------------------------------------------------------

    /** Whole percent of the dial that is used, 0..100. */
    fun percentUsed(m: HealthMetric): Int = (fraction(m) * 100).roundToInt()

    fun formatMb(mb: Double): String =
        if (mb >= 1024) String.format(Locale.US, "%.1f GB", mb / 1024) else "${mb.roundToInt()} MB"

    /** "160 of 427 MB used" (GB once the total is a gigabyte or more). */
    fun usedOfText(m: HealthMetric): String =
        if (m.max >= 1024) "${String.format(Locale.US, "%.1f", m.value / 1024)} of ${formatMb(m.max)} used"
        else "${m.value.roundToInt()} of ${m.max.roundToInt()} MB used"

    fun freeText(m: HealthMetric): String = "${formatMb(max(m.max - m.value, 0.0))} free"

    fun loadWord(level: HealthLevel): String = when (level) {
        HealthLevel.OK -> "light"; HealthLevel.WARN -> "busy"; HealthLevel.ERROR -> "overloaded"; HealthLevel.INFO -> ""
    }

    /** Good (3-4 bars) / Fair (2) / Weak (1 or node WARN) / Very weak (0 or node ERROR); the worse of bars and level wins. */
    fun wifiWord(bars: Int?, level: HealthLevel): String {
        val byBars = bars?.let { when { it >= 3 -> 0; it == 2 -> 1; it == 1 -> 2; else -> 3 } }
        val byLevel = when (level) { HealthLevel.OK -> 0; HealthLevel.WARN -> 2; HealthLevel.ERROR -> 3; HealthLevel.INFO -> null }
        val r = listOfNotNull(byBars, byLevel).maxOrNull() ?: return ""
        return listOf("Good", "Fair", "Weak", "Very weak")[r]
    }

    /** What a ring/bars tile prints: centre value, small unit under it, line under the label, spoken text. */
    data class TileText(val value: String, val unit: String, val sub: String, val description: String)

    fun tileText(id: String, label: String, m: HealthMetric, level: HealthLevel, bars: Int?, stale: Boolean): TileText {
        if (stale) return TileText("—", "", "", "$label, no data")
        val word = statusWord(level, false)
        return when (id) {
            NodeHealthVisual.MEMORY, NodeHealthVisual.DISK, NodeHealthVisual.SWAP -> {
                val sub = if (id == NodeHealthVisual.DISK) freeText(m) else usedOfText(m)
                val pct = percentUsed(m)
                TileText("$pct%", "", sub, "$label $pct percent used, $word, $sub")
            }
            NodeHealthVisual.CPU_LOAD -> {
                val sub = loadWord(level)
                TileText(formatValue(m.value), m.unit, sub, gaugeDescription(label, m, level, false, sub))
            }
            NodeHealthVisual.WIFI -> {
                val sub = wifiWord(bars, level)
                TileText(formatValue(m.value), m.unit, sub, wifiDescription(m, bars, level, false) + if (sub.isEmpty()) "" else ", $sub")
            }
            else -> TileText(formatValue(m.value), m.unit, "", gaugeDescription(label, m, level, false))
        }
    }

    // ---- throttling tile -----------------------------------------------------------------------

    data class ThrottleTile(val tone: Tone, val glyph: String, val value: String, val sub: String, val word: String, val description: String)

    fun glyphFor(t: Tone): String = when (t) { Tone.OK -> "✓"; Tone.WARN -> "!"; Tone.ERROR -> "×"; Tone.GREY -> "–" }

    /**
     * One tile from "Throttling now" and "Throttling since boot". Null when the node can't read it (no item, or an
     * info-level "unavailable"): the plain status lights then carry it. The worse of the two decides the colour.
     */
    fun throttleTile(now: HealthItem?, boot: HealthItem?, stale: Boolean): ThrottleTile? {
        if (now == null || now.level == HealthLevel.INFO) return null
        if (stale) return ThrottleTile(Tone.GREY, glyphFor(Tone.GREY), "—", "", statusWord(now.level, true), "Throttling, no data")
        val bootKnown = boot != null && boot.level != HealthLevel.INFO
        val level = when {
            now.level == HealthLevel.ERROR || (bootKnown && boot!!.level == HealthLevel.ERROR) -> HealthLevel.ERROR
            now.level == HealthLevel.WARN || (bootKnown && boot!!.level == HealthLevel.WARN) -> HealthLevel.WARN
            else -> HealthLevel.OK
        }
        val tone = toneOf(level, false)
        val sub = "since boot: " + if (bootKnown) boot!!.value.lowercase() else "unknown"
        val word = statusWord(level, false)
        return ThrottleTile(tone, glyphFor(tone), now.value, sub, word, "Throttling ${now.value.lowercase()}, $sub, $word")
    }

    /** The flag names for the tile, one per line: at most [max] lines, the rest folded into "+N more". */
    fun throttleLines(value: String, max: Int = 2): List<String> {
        val parts = value.split(", ").map { it.trim().replaceFirstChar { c -> c.uppercase() } }.filter { it.isNotEmpty() }
        if (parts.size <= max) return parts
        return parts.take(max - 1) + "+${parts.size - max + 1} more"
    }

    // ---- sparklines ----------------------------------------------------------------------------

    data class Pt(val x: Float, val y: Float)

    fun sparkVisible(values: List<Double?>): Boolean = values.count { it != null } >= 2

    /** Minimum visible span so a flat line stays flat: temp 5 °C, CPU 20 %, Wi-Fi 10 dB. */
    const val MIN_SPAN_TEMP = 5.0
    const val MIN_SPAN_CPU = 20.0
    const val MIN_SPAN_WIFI = 10.0

    /**
     * Y-axis fitted to the data: its min..max (at least [minSpan] wide) plus 20 % padding each side, so small
     * changes show. With a metric the window slides to stay inside the metric's own min..max when it fits there.
     */
    fun sparkRange(values: List<Double?>, m: HealthMetric?, minSpan: Double): Pair<Double, Double> {
        val v = values.filterNotNull()
        if (v.isEmpty()) return (m?.min ?: 0.0) to (m?.max ?: 1.0)
        val dLo = v.min(); val dHi = v.max()
        val span = max(dHi - dLo, minSpan)
        val mid = (dLo + dHi) / 2
        val half = span / 2 + span * 0.2
        var lo = mid - half; var hi = mid + half
        if (m != null && hi - lo <= m.max - m.min) {
            if (lo < m.min) { hi += m.min - lo; lo = m.min }
            if (hi > m.max) { lo -= hi - m.max; hi = m.max }
        }
        return lo to hi
    }

    /** A threshold line is drawn only when it falls inside the visible range. */
    fun thresholdVisible(t: Double?, lo: Double, hi: Double): Boolean = t != null && t >= lo && t <= hi

    /** Small caption when no threshold line is visible: where the data sits relative to the warning level. Null = nothing to say. */
    fun thresholdCaption(m: HealthMetric?, lo: Double, hi: Double): String? {
        if (m == null) return null
        val t = m.warn ?: m.error ?: return null
        if (thresholdVisible(m.warn, lo, hi) || thresholdVisible(m.error, lo, hi)) return null
        val dataBelow = t > hi
        return if (dataBelow == m.higherIsWorse) (if (dataBelow) "well below the warning level" else "well above the warning level") else "beyond the warning level"
    }

    /** "max 46.5 °C · min 43.8 °C" for the readings in the last hour; null when there are none. */
    fun minMaxLabel(values: List<Double?>, unit: String): String? {
        val v = values.filterNotNull()
        if (v.isEmpty()) return null
        val u = if (unit.isEmpty()) "" else " $unit"
        return "max ${formatValue(v.max())}$u · min ${formatValue(v.min())}$u"
    }

    /** Points in a w×h box (y grows downward). A null reading ends the segment, so the line has a gap there. */
    fun sparkSegments(values: List<Double?>, w: Float, h: Float, lo: Double, hi: Double): List<List<Pt>> {
        if (values.size < 2) return emptyList()
        val out = ArrayList<List<Pt>>()
        var cur = ArrayList<Pt>()
        values.forEachIndexed { i, v ->
            if (v == null) {
                if (cur.isNotEmpty()) out.add(cur)
                cur = ArrayList()
            } else {
                cur.add(Pt(w * i / (values.size - 1), h - h * fraction(v, lo, hi)))
            }
        }
        if (cur.isNotEmpty()) out.add(cur)
        return out
    }

    fun latest(values: List<Double?>): Double? = values.lastOrNull { it != null }

    fun yFor(threshold: Double, h: Float, lo: Double, hi: Double): Float = h - h * fraction(threshold, lo, hi)

    /** Left x-axis label from the sample count: a full hour reads "1 h ago". */
    fun agoLabel(samples: Int, intervalS: Int): String {
        val secs = (samples - 1) * intervalS
        val minutes = (secs / 60.0).roundToInt()
        return if (minutes >= 55) "1 h ago" else if (secs < 60) "just now" else "$minutes min ago"
    }

    fun sparkDescription(label: String, values: List<Double?>, unit: String, level: HealthLevel, stale: Boolean): String {
        val now = latest(values)
        val v = values.filterNotNull()
        if (stale || now == null || v.size < 2) return "$label, no data"
        return "$label over the last hour: now ${formatValue(now)}${spokenUnit(unit)}, ${statusWord(level, false)}. " +
            "Lowest ${formatValue(v.min())}, highest ${formatValue(v.max())}."
    }

    // ---- banner --------------------------------------------------------------------------------

    data class Banner(val title: String, val subtitle: String, val tone: Tone, val glyph: String)

    /** [unreachableReason] non-null = the phone can't trust the node's data: red, never green. */
    fun banner(level: HealthLevel, problems: Int, unreachableReason: String?): Banner = when {
        unreachableReason != null -> Banner("Can't reach the node", unreachableReason, Tone.ERROR, "×")
        level == HealthLevel.ERROR -> Banner("Something is wrong", NodeHealthUi.summary(problems), Tone.ERROR, "×")
        level == HealthLevel.WARN -> Banner("Needs a look", NodeHealthUi.summary(problems), Tone.WARN, "!")
        else -> Banner("All good", NodeHealthUi.summary(problems), Tone.OK, "✓")
    }

    fun bannerDescription(b: Banner, tappable: Boolean): String =
        "${b.title}. ${b.subtitle}." + if (tappable) " Double tap to jump to the first problem." else ""

    // ---- bars (Wi-Fi) --------------------------------------------------------------------------

    fun barFilled(index: Int, bars: Int?): Boolean = bars != null && index < bars
}

// ---- views -----------------------------------------------------------------------------------------

private fun Context.dpf(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, resources.displayMetrics)
private fun Context.spf(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics)

private fun Context.paint(sp: Float, colour: Int, bold: Boolean = false, align: Paint.Align = Paint.Align.LEFT) = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
    textSize = spf(sp); color = colour; isFakeBoldText = bold; textAlign = align
}

private fun Paint.height() = fontMetrics.let { it.descent - it.ascent }
private fun Canvas.textTop(text: String, x: Float, top: Float, p: Paint) = drawText(text, x, top - p.fontMetrics.ascent, p)
private fun clip(text: String, p: TextPaint, w: Float): String = TextUtils.ellipsize(text, p, max(w, 1f), TextUtils.TruncateAt.END).toString()

private fun animatorsOn() = ValueAnimator.areAnimatorsEnabled()

/** Shared 200 ms ease of a 0..1 value; skipped when the system says "remove animations" or the view isn't showing. */
private class Ease(private val view: View, private val onValue: (Float) -> Unit) {
    private var anim: ValueAnimator? = null
    var shown = 0f
        private set

    fun to(target: Float) {
        anim?.cancel()
        if (target == shown) return
        if (!animatorsOn() || !view.isShown) { shown = target; onValue(shown); return }
        anim = ValueAnimator.ofFloat(shown, target).apply {
            duration = 200
            addUpdateListener { shown = it.animatedValue as Float; onValue(shown) }
            start()
        }
    }

    fun cancel() { anim?.cancel() }
}

private const val PAPER = 0xFFFAFAF7.toInt()

/** A tile in the 2-column grid: a ring gauge (value inside, unit below it), Wi-Fi signal bars or a status circle, then label, a plain-word line and the status word. */
class GaugeTileView @JvmOverloads constructor(c: Context, a: AttributeSet? = null) : View(c, a) {
    enum class Kind { RING, BARS, CIRCLE }

    var kind = Kind.RING
    private var label = ""
    private var valueText = "—"
    private var unitText = ""
    private var sub = ""
    private var glyph = ""
    private var lines: List<String> = emptyList()
    private var word = ""
    private var tone = Viz.Tone.GREY
    private var ticks: List<Float> = emptyList()
    private var bars: Int? = null
    private var target = 0f
    private val ease = Ease(this) { invalidate() }

    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Viz.TRACK; strokeCap = Paint.Cap.ROUND }
    private val arc = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
    private val tick = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Viz.INK; alpha = 110 }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val border = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Viz.BORDER }
    private val valueP = c.paint(22f, Viz.INK, true, Paint.Align.CENTER)
    private val unitP = c.paint(12f, Viz.T_GREY, false, Paint.Align.CENTER)
    private val labelP = c.paint(14f, Viz.INK, true, Paint.Align.CENTER)
    private val subP = c.paint(12f, Viz.T_GREY, false, Paint.Align.CENTER)
    private val lineP = c.paint(14f, Viz.INK, true, Paint.Align.CENTER)
    private val glyphP = c.paint(40f, PAPER, true, Paint.Align.CENTER)
    private val wordP = c.paint(13f, Viz.T_GREY, true, Paint.Align.CENTER)
    private val oval = RectF()

    init { isFocusable = true; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES }

    fun set(
        label: String, valueText: String, unit: String, word: String, tone: Viz.Tone, fraction: Float,
        ticks: List<Float> = emptyList(), bars: Int? = null, sub: String = "", description: String,
    ) {
        this.label = label; this.valueText = valueText; this.unitText = unit; this.word = word; this.tone = tone
        this.ticks = ticks; this.bars = bars; this.sub = sub
        target = fraction
        if (contentDescription != description) contentDescription = description
        ease.to(fraction)
        invalidate()
    }

    /** The throttling tile: a big traffic-light circle with a glyph, then the flags and the "since boot" line. */
    fun setCircle(label: String, t: Viz.ThrottleTile) {
        kind = Kind.CIRCLE
        this.label = label; this.glyph = t.glyph; this.lines = Viz.throttleLines(t.value); this.sub = t.sub; this.word = t.word; this.tone = t.tone
        if (contentDescription != t.description) contentDescription = t.description
        requestLayout()
        invalidate()
    }

    private fun ringSize(w: Float): Float {
        val scale = resources.configuration.fontScale.coerceIn(1f, 1.6f)
        return min(w - context.dpf(24f), context.dpf(104f) * scale)
    }

    override fun onMeasure(wSpec: Int, hSpec: Int) {
        val w = when (MeasureSpec.getMode(wSpec)) { MeasureSpec.UNSPECIFIED -> context.dpf(160f).toInt(); else -> MeasureSpec.getSize(wSpec) }
        var h = context.dpf(12f) + ringSize(w.toFloat()) + context.dpf(8f) + labelP.height() + wordP.height() + context.dpf(14f)
        if (sub.isNotEmpty()) h += subP.height()
        if (kind == Kind.CIRCLE) h += lineP.height() * lines.size
        setMeasuredDimension(w, resolveSize(h.toInt(), hSpec))
    }

    override fun onDetachedFromWindow() { ease.cancel(); super.onDetachedFromWindow() }

    override fun onDraw(cv: Canvas) {
        val w = width.toFloat()
        val d = context.dpf(0.75f)
        border.strokeWidth = context.dpf(1.5f)
        cv.drawRect(d, d, w - d, height - d, border)
        val ring = ringSize(w)
        val cx = w / 2
        val top = context.dpf(12f)
        val col = Viz.colour(tone)
        when (kind) { Kind.RING -> drawRing(cv, cx, top, ring, col); Kind.BARS -> drawBars(cv, cx, top, ring, col); Kind.CIRCLE -> drawCircle(cv, cx, top, ring, col) }
        var y = top + ring + context.dpf(8f)
        labelP.color = Viz.INK
        cv.textTop(clip(label, labelP, w - context.dpf(16f)), cx, y, labelP)
        y += labelP.height()
        if (kind == Kind.CIRCLE) lines.forEach {
            cv.textTop(clip(it, lineP, w - context.dpf(16f)), cx, y, lineP)
            y += lineP.height()
        }
        if (sub.isNotEmpty()) {
            cv.textTop(clip(sub, subP, w - context.dpf(16f)), cx, y, subP)
            y += subP.height()
        }
        wordP.color = Viz.textColour(tone)
        cv.textTop(word, cx, y, wordP)
    }

    private fun drawRing(cv: Canvas, cx: Float, top: Float, d: Float, col: Int) {
        val sw = context.dpf(10f)
        track.strokeWidth = sw; arc.strokeWidth = sw; arc.color = col
        tick.strokeWidth = context.dpf(2f)
        val r = d / 2 - sw / 2 - context.dpf(2f)
        val cy = top + d / 2
        oval.set(cx - r, cy - r, cx + r, cy + r)
        cv.drawArc(oval, Viz.RING_START, Viz.RING_SWEEP, false, track)
        val shown = ease.shown
        if (shown > 0.005f) cv.drawArc(oval, Viz.RING_START, Viz.RING_SWEEP * shown, false, arc)
        ticks.forEach {
            val a = Math.toRadians(Viz.angleAt(it).toDouble())
            val r1 = r - sw / 2 - context.dpf(3f)
            val r2 = r + sw / 2 + context.dpf(3f)
            cv.drawLine((cx + r1 * Math.cos(a)).toFloat(), (cy + r1 * Math.sin(a)).toFloat(), (cx + r2 * Math.cos(a)).toFloat(), (cy + r2 * Math.sin(a)).toFloat(), tick)
        }
        valueP.color = if (tone == Viz.Tone.GREY && valueText == "—") Viz.T_GREY else Viz.INK
        val inner = (r - sw) * 2 - context.dpf(6f)
        valueP.textSize = context.spf(22f)
        while (valueP.measureText(valueText) > inner && valueP.textSize > context.spf(12f)) valueP.textSize -= context.spf(1f)
        val vh = valueP.height()
        val uh = if (unitText.isEmpty()) 0f else unitP.height()
        val y0 = cy - (vh + uh) / 2
        cv.textTop(valueText, cx, y0, valueP)
        if (unitText.isNotEmpty()) cv.textTop(clip(unitText, unitP, inner), cx, y0 + vh, unitP)
    }

    private fun drawCircle(cv: Canvas, cx: Float, top: Float, d: Float, col: Int) {
        val r = d / 2 - context.dpf(4f)
        val cy = top + d / 2
        fill.color = col
        cv.drawCircle(cx, cy, r, fill)
        glyphP.textSize = r * 1.15f
        glyphP.color = PAPER
        cv.drawText(glyph, cx, cy - (glyphP.fontMetrics.ascent + glyphP.fontMetrics.descent) / 2, glyphP)
    }

    private fun drawBars(cv: Canvas, cx: Float, top: Float, d: Float, col: Int) {
        val bw = context.dpf(14f)
        val gap = context.dpf(7f)
        val total = 4 * bw + 3 * gap
        val maxH = d * 0.52f
        val baseY = top + d * 0.62f
        for (i in 0 until 4) {
            val bh = maxH * (i + 1) / 4
            val x = cx - total / 2 + i * (bw + gap)
            fill.color = if (Viz.barFilled(i, bars)) col else Viz.TRACK
            cv.drawRoundRect(x, baseY - bh, x + bw, baseY, context.dpf(2f), context.dpf(2f), fill)
        }
        valueP.color = if (valueText == "—") Viz.T_GREY else Viz.INK
        valueP.textSize = context.spf(15f)
        val dbm = if (valueText == "—") "—" else "$valueText $unitText".trim()
        cv.textTop(clip(dbm, valueP, d + context.dpf(24f)), cx, baseY + context.dpf(6f), valueP)
    }
}

/** Compact horizontal bar gauge: label and value on the first line, then the bar with its status word. */
class BarGaugeView @JvmOverloads constructor(c: Context, a: AttributeSet? = null) : View(c, a) {
    private var label = ""
    private var valueText = "—"
    private var word = ""
    private var tone = Viz.Tone.GREY
    private var ticks: List<Float> = emptyList()
    private val ease = Ease(this) { invalidate() }
    private val labelP = c.paint(14f, Viz.T_GREY)
    private val valueP = c.paint(15f, Viz.INK, true, Paint.Align.RIGHT)
    private val wordP = c.paint(13f, Viz.T_GREY, true, Paint.Align.RIGHT)
    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Viz.TRACK }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val tick = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Viz.INK; alpha = 110 }

    init { isFocusable = true; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES }

    fun set(label: String, valueText: String, word: String, tone: Viz.Tone, fraction: Float, ticks: List<Float>, description: String) {
        this.label = label; this.valueText = valueText; this.word = word; this.tone = tone; this.ticks = ticks
        if (contentDescription != description) contentDescription = description
        ease.to(fraction)
        invalidate()
    }

    private fun wordWidth() = context.dpf(64f) * resources.configuration.fontScale.coerceIn(1f, 1.6f)

    override fun onMeasure(wSpec: Int, hSpec: Int) {
        val h = context.dpf(10f) + valueP.height() + context.dpf(6f) + max(context.dpf(12f), wordP.height()) + context.dpf(10f)
        setMeasuredDimension(resolveSize(context.dpf(240f).toInt(), wSpec), resolveSize(max(h, context.dpf(56f)).toInt(), hSpec))
    }

    override fun onDetachedFromWindow() { ease.cancel(); super.onDetachedFromWindow() }

    override fun onDraw(cv: Canvas) {
        val w = width.toFloat()
        var y = context.dpf(10f)
        valueP.color = Viz.INK
        cv.textTop(clip(label, labelP, w * 0.5f), 0f, y, labelP)
        cv.textTop(clip(valueText, valueP, w * 0.5f), w, y, valueP)
        y += valueP.height() + context.dpf(6f)
        val bh = context.dpf(12f)
        val barW = w - wordWidth() - context.dpf(10f)
        val cy = y + max(bh, wordP.height()) / 2
        val r = bh / 2
        cv.drawRoundRect(0f, cy - r, barW, cy + r, r, r, track)
        fill.color = Viz.colour(tone)
        if (ease.shown > 0.005f) cv.drawRoundRect(0f, cy - r, max(barW * ease.shown, bh), cy + r, r, r, fill)
        tick.strokeWidth = context.dpf(2f)
        ticks.forEach { cv.drawLine(barW * it, cy - r - context.dpf(2f), barW * it, cy + r + context.dpf(2f), tick) }
        wordP.color = Viz.textColour(tone)
        cv.drawText(word, w, cy - (wordP.fontMetrics.ascent + wordP.fontMetrics.descent) / 2, wordP)
    }
}

/** Last-hour line with a soft fill, dashed warn/error thresholds, the latest value and an "N ago … now" axis. */
class SparklineView @JvmOverloads constructor(c: Context, a: AttributeSet? = null) : View(c, a) {
    private var title = ""
    private var unit = ""
    private var values: List<Double?> = emptyList()
    private var range = 0.0 to 1.0
    private var warn: Double? = null
    private var error: Double? = null
    private var tone = Viz.Tone.GREY
    private var intervalS = 30
    private var stale = false
    private var caption: String? = null
    private var minMax: String? = null
    private val titleP = c.paint(14f, Viz.T_GREY)
    private val valueP = c.paint(15f, Viz.INK, true, Paint.Align.RIGHT)
    private val axisP = c.paint(12f, Viz.T_GREY)
    private val line = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeJoin = Paint.Join.ROUND; strokeCap = Paint.Cap.ROUND }
    private val area = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val dash = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val frame = Paint().apply { color = Viz.BORDER }
    private val path = Path()

    init { isFocusable = true; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES }

    fun set(title: String, values: List<Double?>, m: HealthMetric?, unit: String, tone: Viz.Tone, intervalS: Int, stale: Boolean, minSpan: Double, description: String) {
        this.stale = stale; this.title = title; this.values = values; this.unit = unit; this.tone = tone; this.intervalS = intervalS
        range = Viz.sparkRange(values, m, minSpan)
        warn = m?.warn; error = m?.error
        caption = Viz.thresholdCaption(m, range.first, range.second)
        minMax = Viz.minMaxLabel(values, unit)
        requestLayout()
        if (contentDescription != description) contentDescription = description
        invalidate()
    }

    private fun plotH() = context.dpf(64f)

    /** Axis row, plus a row for max/min and one for the threshold caption when there is something to say. */
    private fun extraAxisLines() = 1 + (if (minMax != null) 1 else 0) + (if (caption != null) 1 else 0)

    override fun onMeasure(wSpec: Int, hSpec: Int) {
        val h = context.dpf(8f) + valueP.height() + context.dpf(8f) + plotH() + context.dpf(4f) + axisP.height() * extraAxisLines() + context.dpf(8f)
        setMeasuredDimension(resolveSize(context.dpf(240f).toInt(), wSpec), resolveSize(h.toInt(), hSpec))
    }

    override fun onDraw(cv: Canvas) {
        val w = width.toFloat()
        var y = context.dpf(8f)
        val latest = Viz.latest(values)
        valueP.color = Viz.textColour(tone)
        cv.textTop(clip(title, titleP, w * 0.55f), 0f, y, titleP)
        cv.textTop(if (latest == null || stale) "—" else "${Viz.formatValue(latest)} $unit".trim(), w, y, valueP)
        y += valueP.height() + context.dpf(8f)
        val h = plotH()
        val (lo, hi) = range
        cv.drawRect(0f, y + h, w, y + h + context.dpf(1f), frame)
        // thresholds first so the data line sits on top
        dash.strokeWidth = context.dpf(1.5f)
        dash.pathEffect = DashPathEffect(floatArrayOf(context.dpf(5f), context.dpf(4f)), 0f)
        listOf(warn to Viz.C_WARN, error to Viz.C_ERROR).forEach { (t, col) ->
            if (Viz.thresholdVisible(t, lo, hi)) {
                dash.color = col
                val ty = y + Viz.yFor(t!!, h, lo, hi)
                cv.drawLine(0f, ty, w, ty, dash)
            }
        }
        val col = Viz.colour(tone)
        line.color = col; line.strokeWidth = context.dpf(2.5f)
        area.color = (col and 0x00FFFFFF) or 0x2E000000
        val pad = context.dpf(3f)
        Viz.sparkSegments(values, w - 2 * pad, h - 2 * pad, lo, hi).forEach { seg ->
            if (seg.size == 1) {
                dot.color = col
                cv.drawCircle(pad + seg[0].x, y + pad + seg[0].y, context.dpf(2.5f), dot)
                return@forEach
            }
            path.rewind()
            seg.forEachIndexed { i, p -> if (i == 0) path.moveTo(pad + p.x, y + pad + p.y) else path.lineTo(pad + p.x, y + pad + p.y) }
            val stroke = Path(path)
            path.lineTo(pad + seg.last().x, y + h); path.lineTo(pad + seg.first().x, y + h); path.close()
            cv.drawPath(path, area)
            cv.drawPath(stroke, line)
        }
        y += h + context.dpf(4f)
        axisP.textAlign = Paint.Align.LEFT
        cv.textTop(Viz.agoLabel(values.size, intervalS), 0f, y, axisP)
        axisP.textAlign = Paint.Align.RIGHT
        cv.textTop("now", w, y, axisP)
        y += axisP.height()
        minMax?.let { cv.textTop(clip(it, axisP, w), w, y, axisP); y += axisP.height() }
        caption?.let {
            axisP.textAlign = Paint.Align.LEFT
            cv.textTop(clip(it, axisP, w), 0f, y, axisP)
        }
    }

}

/** Small donut: ok vs failed, with the total in the middle. */
class DonutView @JvmOverloads constructor(c: Context, a: AttributeSet? = null) : View(c, a) {
    private var ok = 0
    private var failed = 0
    private var stale = true
    private val track = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; color = Viz.TRACK }
    private val seg = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val totalP = c.paint(18f, Viz.INK, true, Paint.Align.CENTER)
    private val oval = RectF()

    init { isFocusable = true; importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES }

    fun set(counts: RedirectCounts?, stale: Boolean, description: String) {
        ok = counts?.ok ?: 0; failed = counts?.failed ?: 0; this.stale = stale || counts == null
        if (contentDescription != description) contentDescription = description
        invalidate()
    }

    override fun onMeasure(wSpec: Int, hSpec: Int) {
        val s = (context.dpf(76f) * resources.configuration.fontScale.coerceIn(1f, 1.4f)).toInt()
        setMeasuredDimension(resolveSize(s, wSpec), resolveSize(s, hSpec))
    }

    override fun onDraw(cv: Canvas) {
        val sw = context.dpf(11f)
        val r = min(width, height) / 2f - sw / 2 - context.dpf(2f)
        val cx = width / 2f; val cy = height / 2f
        oval.set(cx - r, cy - r, cx + r, cy + r)
        track.strokeWidth = sw; seg.strokeWidth = sw
        cv.drawOval(oval, track)
        val total = ok + failed
        if (total > 0) {
            val fShare = Viz.failedShare(ok, failed)
            val okSweep = 360f * (1 - fShare)
            seg.color = if (stale) Viz.C_GREY else Viz.C_OK
            if (okSweep > 0f) cv.drawArc(oval, -90f, okSweep, false, seg)
            seg.color = if (stale) Viz.C_GREY else Viz.C_ERROR
            if (fShare > 0f) cv.drawArc(oval, -90f + okSweep, 360f * fShare, false, seg)
        }
        totalP.color = if (stale) Viz.T_GREY else Viz.INK
        cv.textTop(if (stale) "—" else total.toString(), cx, cy - totalP.height() / 2, totalP)
    }
}
