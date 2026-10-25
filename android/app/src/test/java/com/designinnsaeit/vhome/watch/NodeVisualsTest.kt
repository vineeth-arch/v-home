package com.designinnsaeit.vhome.watch

import com.designinnsaeit.vhome.watch.Viz.Tone
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeVisualsTest {
    private val sample = """
    {"level":"warn","problems":1,"age_s":0.4,"items":[
      {"group":"pi","key":"temp","label":"Temperature","value":"45.1 °C","level":"ok","detail":"",
       "metric":{"value":45.1,"min":0,"max":85,"unit":"°C","warn":65,"error":75,"higher_is_worse":true}},
      {"group":"pi","key":"cpu_use","label":"CPU use","value":"12 %","level":"info","detail":"",
       "metric":{"value":12,"min":0,"max":100,"unit":"%","higher_is_worse":true}},
      {"group":"pi","key":"swap","label":"Swap","value":"0 MB","level":"ok","detail":"",
       "metric":{"value":0,"min":0,"max":100,"unit":"MB","warn":50,"higher_is_worse":true}},
      {"group":"network","key":"wifi_signal","label":"Wi-Fi signal","value":"-60 dBm","level":"ok","detail":"",
       "metric":{"value":-60,"min":-95,"max":-30,"unit":"dBm","warn":-75,"error":-85,"higher_is_worse":false,"bars":3}},
      {"group":"watcher","key":"redirects","label":"Redirects","value":"7 ok","level":"warn","detail":"2 failed","counts":{"ok":7,"failed":2}},
      {"group":"node","key":"clock","label":"Clock","value":"synced","level":"ok","detail":""}
    ],
    "history":{"interval_s":30,"temp":[44.0,null,45.0,46.0],"cpu_use":[],"load":[],"mem_used_mb":[],"wifi_dbm":[-60,-61]}}
    """

    private fun m(v: Double, lo: Double = 0.0, hi: Double = 100.0, warn: Double? = null, err: Double? = null, hw: Boolean = true) =
        HealthMetric(v, lo, hi, "", warn, err, hw)

    // ---- colours and words
    @Test fun levelToTone() {
        assertEquals(Tone.OK, Viz.toneOf(HealthLevel.OK, false))
        assertEquals(Tone.WARN, Viz.toneOf(HealthLevel.WARN, false))
        assertEquals(Tone.ERROR, Viz.toneOf(HealthLevel.ERROR, false))
        assertEquals(Tone.GREY, Viz.toneOf(HealthLevel.INFO, false))
    }

    @Test fun staleIsAlwaysGrey() {
        HealthLevel.values().forEach { assertEquals(Tone.GREY, Viz.toneOf(it, true)) }
        assertEquals("No data", Viz.statusWord(HealthLevel.OK, true))
    }

    @Test fun coloursAreDistinctAndGreenIsContrastSafe() {
        assertEquals(4, Tone.values().map { Viz.colour(it) }.toSet().size)
        assertEquals(0xFF1E7B34.toInt(), Viz.colour(Tone.OK))
        assertEquals(0xFF8A5A00.toInt(), Viz.colour(Tone.WARN))
        assertEquals(0xFFD62828.toInt(), Viz.colour(Tone.ERROR))
    }

    @Test fun contrastOfTextColoursOnPaperIsAtLeast4_5() {
        val paper = 0xFFFAFAF7.toInt()
        Tone.values().forEach { assertTrue("$it", contrast(Viz.textColour(it), paper) >= 4.5) }
    }

    @Test fun statusWords() {
        assertEquals("OK", Viz.statusWord(HealthLevel.OK, false))
        assertEquals("Check", Viz.statusWord(HealthLevel.WARN, false))
        assertEquals("Problem", Viz.statusWord(HealthLevel.ERROR, false))
        assertEquals("Info", Viz.statusWord(HealthLevel.INFO, false))
    }

    // ---- gauge maths
    @Test fun fractionIsClamped() {
        assertEquals(0.5f, Viz.fraction(42.5, 0.0, 85.0), 1e-6f)
        assertEquals(0f, Viz.fraction(-5.0, 0.0, 85.0), 0f)
        assertEquals(1f, Viz.fraction(200.0, 0.0, 85.0), 0f)
        assertEquals(0f, Viz.fraction(3.0, 5.0, 5.0), 0f)
    }

    @Test fun wifiFillsWithStrongerSignal() {
        val w = m(-62.5, -95.0, -30.0, -75.0, -85.0, hw = false)
        assertEquals(0.5f, Viz.fraction(w), 1e-6f)
        assertTrue(Viz.fraction(m(-40.0, -95.0, -30.0, hw = false)) > Viz.fraction(w))
    }

    @Test fun thresholdTicks() {
        val t = Viz.tickFractions(m(45.0, 0.0, 85.0, 65.0, 75.0))
        assertEquals(listOf((65 / 85.0).toFloat(), (75 / 85.0).toFloat()), t)
        assertEquals(listOf(0.5f), Viz.tickFractions(m(0.0, 0.0, 100.0, warn = 50.0)))
        assertTrue(Viz.tickFractions(m(0.0)).isEmpty())
        assertEquals(listOf(20f / 65f, 10f / 65f), Viz.tickFractions(m(-60.0, -95.0, -30.0, -75.0, -85.0, false)))
    }

    @Test fun ringAngles() {
        assertEquals(135f, Viz.angleAt(0f), 0f)
        assertEquals(270f, Viz.angleAt(0.5f), 0f)
        assertEquals(405f, Viz.angleAt(1f), 0f)
    }

    @Test fun valueFormatting() {
        assertEquals("45.1", Viz.formatValue(45.1))
        assertEquals("45", Viz.formatValue(45.0))
        assertEquals("-60", Viz.formatValue(-60.0))
        assertEquals("1400", Viz.formatValue(1400.0))
        assertEquals("212", Viz.formatValue(212.4))
    }

    // ---- sparklines
    @Test fun sparklineNeedsTwoPoints() {
        assertFalse(Viz.sparkVisible(emptyList()))
        assertFalse(Viz.sparkVisible(listOf(1.0)))
        assertFalse(Viz.sparkVisible(listOf(1.0, null, null)))
        assertTrue(Viz.sparkVisible(listOf(1.0, null, 2.0)))
    }

    @Test fun sparklineMappingWithGap() {
        val segs = Viz.sparkSegments(listOf(0.0, 50.0, null, 100.0, 100.0), 100f, 40f, 0.0, 100.0)
        assertEquals(2, segs.size)
        assertEquals(Viz.Pt(0f, 40f), segs[0][0])
        assertEquals(Viz.Pt(25f, 20f), segs[0][1])
        assertEquals(Viz.Pt(75f, 0f), segs[1][0])
        assertEquals(Viz.Pt(100f, 0f), segs[1][1])
        assertTrue(Viz.sparkSegments(listOf(1.0), 10f, 10f, 0.0, 2.0).isEmpty())
    }

    @Test fun sparkRangeAutoScalesWithPaddingAndMinSpan() {
        val t = m(45.0, 0.0, 85.0, 65.0, 75.0)
        // 43.8..46.5 is narrower than the 5 °C minimum: 5 °C span centred on 45.15, +20 % each side
        val (lo, hi) = Viz.sparkRange(listOf(43.8, 45.0, 46.5), t, Viz.MIN_SPAN_TEMP)
        assertEquals(7.0, hi - lo, 1e-9)
        assertEquals(45.15, (lo + hi) / 2, 1e-9)
        // a wide swing is not widened, only padded by 20 % of its own span
        val (l2, h2) = Viz.sparkRange(listOf(30.0, 50.0), t, Viz.MIN_SPAN_TEMP)
        assertEquals(28.0, h2 - l2, 1e-9); assertEquals(26.0, l2, 1e-9); assertEquals(54.0, h2, 1e-9)
        // CPU and Wi-Fi minimum spans
        val c = Viz.sparkRange(listOf(10.0, 11.0), m(10.0, 0.0, 100.0, 80.0, 95.0), Viz.MIN_SPAN_CPU)
        assertEquals(28.0, c.second - c.first, 1e-9)
        val w = Viz.sparkRange(listOf(-60.0, -61.0), m(-60.0, -95.0, -30.0, -75.0, -85.0, false), Viz.MIN_SPAN_WIFI)
        assertEquals(14.0, w.second - w.first, 1e-9)
    }

    @Test fun sparkRangeStaysInsideTheMetricScale() {
        val (lo, hi) = Viz.sparkRange(listOf(0.0, 1.0), m(0.0, 0.0, 100.0, 80.0, 95.0), Viz.MIN_SPAN_CPU)
        assertEquals(0.0, lo, 1e-9); assertEquals(28.0, hi, 1e-9)
        val (l2, h2) = Viz.sparkRange(listOf(99.0, 100.0), m(99.0, 0.0, 100.0, 80.0, 95.0), Viz.MIN_SPAN_CPU)
        assertEquals(100.0, h2, 1e-9); assertEquals(72.0, l2, 1e-9)
        // no metric: plain padding, no clamping
        val (l3, _) = Viz.sparkRange(listOf(0.0, 1.0), null, Viz.MIN_SPAN_CPU)
        assertTrue(l3 < 0.0)
        assertEquals(20.0, Viz.latest(listOf(10.0, 20.0, null))!!, 0.0)
        assertEquals(20f, Viz.yFor(50.0, 40f, 0.0, 100.0), 0f)
    }

    @Test fun thresholdLineOnlyWhenInsideTheVisibleRange() {
        assertTrue(Viz.thresholdVisible(65.0, 40.0, 70.0))
        assertTrue(Viz.thresholdVisible(70.0, 40.0, 70.0))
        assertFalse(Viz.thresholdVisible(75.0, 40.0, 70.0))
        assertFalse(Viz.thresholdVisible(null, 40.0, 70.0))
    }

    @Test fun thresholdCaptionWhenNoLineIsVisible() {
        val temp = m(45.0, 0.0, 85.0, 65.0, 75.0)
        assertEquals("well below the warning level", Viz.thresholdCaption(temp, 41.0, 49.0))
        assertNull(Viz.thresholdCaption(temp, 55.0, 70.0))          // warn line is drawn
        val wifi = m(-60.0, -95.0, -30.0, -75.0, -85.0, false)
        assertEquals("well above the warning level", Viz.thresholdCaption(wifi, -65.0, -55.0))
        assertNull(Viz.thresholdCaption(wifi, -80.0, -55.0))
        assertEquals("beyond the warning level", Viz.thresholdCaption(temp, 80.0, 84.0))
        assertNull(Viz.thresholdCaption(m(1.0), 0.0, 5.0))           // no thresholds at all
        assertNull(Viz.thresholdCaption(null, 0.0, 5.0))
    }

    @Test fun minMaxLabel() {
        assertEquals("max 46.5 °C · min 43.8 °C", Viz.minMaxLabel(listOf(44.0, null, 46.5, 43.8), "°C"))
        assertEquals("max -58 dBm · min -64 dBm", Viz.minMaxLabel(listOf(-60.0, -58.0, -64.0), "dBm"))
        assertNull(Viz.minMaxLabel(listOf(null, null), "°C"))
    }

    @Test fun axisLabel() {
        assertEquals("1 h ago", Viz.agoLabel(120, 30))
        assertEquals("30 min ago", Viz.agoLabel(61, 30))
        assertEquals("just now", Viz.agoLabel(2, 30))
    }

    // ---- banner
    @Test fun bannerStates() {
        val ok = Viz.banner(HealthLevel.OK, 0, null)
        assertEquals("All good", ok.title); assertEquals(Tone.OK, ok.tone); assertEquals("Everything is working", ok.subtitle)
        val info = Viz.banner(HealthLevel.INFO, 0, null)
        assertEquals(Tone.OK, info.tone)
        val warn = Viz.banner(HealthLevel.WARN, 2, null)
        assertEquals("Needs a look", warn.title); assertEquals(Tone.WARN, warn.tone); assertEquals("2 problems", warn.subtitle)
        val err = Viz.banner(HealthLevel.ERROR, 1, null)
        assertEquals("Something is wrong", err.title); assertEquals(Tone.ERROR, err.tone); assertEquals("1 problem", err.subtitle)
    }

    @Test fun unreachableBannerIsRedNeverGreen() {
        val b = Viz.banner(HealthLevel.OK, 0, "Last seen 10:42")
        assertEquals("Can't reach the node", b.title)
        assertEquals(Tone.ERROR, b.tone)
        assertEquals("Last seen 10:42", b.subtitle)
        assertTrue(Viz.bannerDescription(b, true).contains("jump to the first problem"))
        assertFalse(Viz.bannerDescription(Viz.banner(HealthLevel.OK, 0, null), false).contains("jump"))
    }

    // ---- TalkBack text
    @Test fun descriptions() {
        val t = HealthMetric(45.1, 0.0, 85.0, "°C", 65.0, 75.0, true)
        assertEquals("Temperature 45.1 degrees, OK", Viz.gaugeDescription("Temperature", t, HealthLevel.OK, false))
        assertEquals("Temperature 80 degrees, Problem", Viz.gaugeDescription("Temperature", t.copy(value = 80.0), HealthLevel.ERROR, false))
        assertEquals("Temperature, no data", Viz.gaugeDescription("Temperature", t, HealthLevel.OK, true))
        val w = HealthMetric(-60.0, -95.0, -30.0, "dBm", -75.0, -85.0, false)
        assertEquals("Wi-Fi signal 3 of 4 bars, -60 decibel milliwatts, OK", Viz.wifiDescription(w, 3, HealthLevel.OK, false))
        assertEquals("Wi-Fi, no data", Viz.wifiDescription(w, 3, HealthLevel.OK, true))
        assertEquals("Redirects: 7 ok, 2 failed", Viz.donutDescription(RedirectCounts(7, 2), false))
        assertEquals("Redirects, no data", Viz.donutDescription(RedirectCounts(7, 2), true))
        val d = Viz.sparkDescription("Temperature", listOf(40.0, null, 46.0), "°C", HealthLevel.OK, false)
        assertTrue(d.startsWith("Temperature over the last hour: now 46 degrees, OK."))
        assertEquals("Temperature, no data", Viz.sparkDescription("Temperature", listOf(40.0), "°C", HealthLevel.OK, false))
    }

    @Test fun donutShare() {
        assertEquals(0f, Viz.failedShare(0, 0), 0f)
        assertEquals(0.25f, Viz.failedShare(3, 1), 0f)
        assertEquals("7 ok · 2 failed", Viz.redirectsText(RedirectCounts(7, 2)))
    }

    @Test fun barsFilled() {
        assertTrue(Viz.barFilled(0, 1)); assertFalse(Viz.barFilled(1, 1)); assertFalse(Viz.barFilled(0, null))
    }

    // ---- parsing
    @Test fun parsesVisualFields() {
        val v = NodeHealthVisual.parse(JSONObject(sample))
        val temp = v.metric("pi", "temp")!!
        assertEquals(45.1, temp.value, 0.0); assertEquals(65.0, temp.warn!!, 0.0); assertEquals(75.0, temp.error!!, 0.0)
        assertTrue(temp.higherIsWorse)
        val cpu = v.metric("pi", "cpu_use")!!
        assertNull(cpu.warn); assertNull(cpu.error)
        assertNull(v.metric("pi", "swap")!!.error)
        assertFalse(v.metric("network", "wifi_signal")!!.higherIsWorse)
        assertEquals(3, v.bars)
        assertEquals(RedirectCounts(7, 2), v.redirects)
        assertNull(v.metric("node", "clock"))
        val h = v.history!!
        assertEquals(30, h.intervalS)
        assertEquals(listOf(44.0, null, 45.0, 46.0), h.temp)
        assertTrue(h.cpuUse.isEmpty())
        assertEquals(listOf(-60.0, -61.0), h.wifiDbm)
    }

    @Test fun itemLevelBarsAccepted() {
        val o = JSONObject("""{"items":[{"group":"network","key":"wifi_signal","bars":2,"metric":{"value":-70,"min":-95,"max":-30}}]}""")
        assertEquals(2, NodeHealthVisual.parse(o).bars)
    }

    @Test fun olderNodeHasNoVisuals() {
        val o = JSONObject("""{"level":"ok","problems":0,"items":[{"group":"pi","key":"temp","label":"Temperature","value":"45 °C","level":"ok","detail":""}]}""")
        val v = NodeHealthVisual.parse(o)
        assertTrue(v.metrics.isEmpty()); assertNull(v.bars); assertNull(v.redirects); assertNull(v.history)
        assertNotNull(NodeHealth.parse(o))
        val item = NodeHealth.parse(o).items[0]
        assertFalse(NodeHealthVisual.isVisual(item, v))
        assertFalse(NodeHealthVisual.isVisual(item, null))
    }

    @Test fun badMetricIsIgnored() {
        val o = JSONObject("""{"items":[{"group":"pi","key":"temp","metric":{"value":1,"min":5,"max":5}},{"group":"pi","key":"memory","metric":{"min":0,"max":9}}]}""")
        assertTrue(NodeHealthVisual.parse(o).metrics.isEmpty())
    }

    @Test fun lightsExcludeGaugedItems() {
        val o = JSONObject(sample)
        val v = NodeHealthVisual.parse(o)
        val items = NodeHealth.parse(o).items
        val groups = items.groupBy { it.group }.map { it.key to it.value }
        val lights = NodeHealthVisual.lights(groups, v)
        assertEquals(listOf("node"), lights.map { it.first })
        assertEquals(listOf("clock"), lights.flatMap { it.second }.map { it.key })
        assertEquals(groups, NodeHealthVisual.lights(groups, null))
    }

    @Test fun existingNodeHealthStillParsesWithVisualKeys() {
        val h = NodeHealth.parse(JSONObject(sample))
        assertEquals(6, h.items.size)
        assertNotEquals(HealthLevel.INFO, h.level)
    }

    // ---- plain-word tiles
    @Test fun percentFormatting() {
        val mem = HealthMetric(160.0, 0.0, 427.0, "MB", 367.0, 397.0, true)
        assertEquals(37, Viz.percentUsed(mem))
        val t = Viz.tileText(NodeHealthVisual.MEMORY, "Memory", mem, HealthLevel.OK, null, false)
        assertEquals("37%", t.value); assertEquals("", t.unit); assertEquals("160 of 427 MB used", t.sub)
        assertEquals("Memory 37 percent used, OK, 160 of 427 MB used", t.description)
        assertEquals(100, Viz.percentUsed(mem.copy(value = 900.0)))
        assertEquals("0 of 100 MB used", Viz.tileText(NodeHealthVisual.SWAP, "Swap", HealthMetric(0.0, 0.0, 100.0, "MB", 50.0, null, true), HealthLevel.OK, null, false).sub)
        assertEquals("1.0 of 3.8 GB used", Viz.usedOfText(HealthMetric(1024.0, 0.0, 3900.0, "MB", null, null, true)))
    }

    @Test fun storageShowsFreeSpace() {
        val disk = HealthMetric(1000.0, 0.0, 1846.0, "MB", null, null, true)
        val t = Viz.tileText(NodeHealthVisual.DISK, "Storage", disk, HealthLevel.OK, null, false)
        assertEquals("54%", t.value); assertEquals("846 MB free", t.sub)
        assertEquals("14.0 GB free", Viz.freeText(HealthMetric(2000.0, 0.0, 16384.0, "MB", null, null, true)))
    }

    @Test fun cpuLoadWordsFollowTheLevel() {
        val load = HealthMetric(0.4, 0.0, 4.0, "", 1.5, 3.0, true)
        assertEquals("light", Viz.tileText(NodeHealthVisual.CPU_LOAD, "CPU load", load, HealthLevel.OK, null, false).sub)
        assertEquals("busy", Viz.loadWord(HealthLevel.WARN))
        assertEquals("overloaded", Viz.loadWord(HealthLevel.ERROR))
        assertEquals("", Viz.loadWord(HealthLevel.INFO))
        assertEquals("0.4", Viz.tileText(NodeHealthVisual.CPU_LOAD, "CPU load", load, HealthLevel.OK, null, false).value)
    }

    @Test fun temperatureKeepsItsNumber() {
        val t = Viz.tileText(NodeHealthVisual.TEMP, "Temperature", HealthMetric(44.4, 0.0, 85.0, "°C", 65.0, 75.0, true), HealthLevel.OK, null, false)
        assertEquals("44.4", t.value); assertEquals("°C", t.unit); assertEquals("", t.sub)
    }

    @Test fun wifiWordCombinesBarsAndLevel() {
        assertEquals("Good", Viz.wifiWord(4, HealthLevel.OK)); assertEquals("Good", Viz.wifiWord(3, HealthLevel.OK))
        assertEquals("Fair", Viz.wifiWord(2, HealthLevel.OK))
        assertEquals("Weak", Viz.wifiWord(1, HealthLevel.OK)); assertEquals("Very weak", Viz.wifiWord(0, HealthLevel.OK))
        assertEquals("Weak", Viz.wifiWord(4, HealthLevel.WARN))        // the level can only make it worse
        assertEquals("Very weak", Viz.wifiWord(3, HealthLevel.ERROR))
        assertEquals("Weak", Viz.wifiWord(null, HealthLevel.WARN))
        assertEquals("", Viz.wifiWord(null, HealthLevel.INFO))
    }

    @Test fun staleTilesShowNoData() {
        val t = Viz.tileText(NodeHealthVisual.MEMORY, "Memory", HealthMetric(160.0, 0.0, 427.0, "MB", null, null, true), HealthLevel.OK, null, true)
        assertEquals("—", t.value); assertEquals("", t.sub); assertEquals("Memory, no data", t.description)
    }

    // ---- throttling tile
    private fun item(key: String, value: String, level: HealthLevel) = HealthItem("pi", key, key, value, level, "")

    @Test fun throttlingTileComposition() {
        val ok = Viz.throttleTile(item("throttle_now", "None", HealthLevel.OK), item("throttle_boot", "None", HealthLevel.OK), false)!!
        assertEquals(Tone.OK, ok.tone); assertEquals("✓", ok.glyph); assertEquals("None", ok.value); assertEquals("since boot: none", ok.sub); assertEquals("OK", ok.word)

        val earlier = Viz.throttleTile(item("throttle_now", "None", HealthLevel.OK), item("throttle_boot", "Under-voltage", HealthLevel.WARN), false)!!
        assertEquals(Tone.WARN, earlier.tone); assertEquals("!", earlier.glyph); assertEquals("since boot: under-voltage", earlier.sub)

        val bad = Viz.throttleTile(item("throttle_now", "Under-voltage, throttled", HealthLevel.ERROR), item("throttle_boot", "Under-voltage", HealthLevel.WARN), false)!!
        assertEquals(Tone.ERROR, bad.tone); assertEquals("×", bad.glyph); assertEquals("Under-voltage, throttled", bad.value)
        assertTrue(bad.description.contains("Problem"))

        val noBoot = Viz.throttleTile(item("throttle_now", "None", HealthLevel.OK), item("throttle_boot", "unavailable", HealthLevel.INFO), false)!!
        assertEquals("since boot: unknown", noBoot.sub); assertEquals(Tone.OK, noBoot.tone)
        assertEquals("since boot: unknown", Viz.throttleTile(item("throttle_now", "None", HealthLevel.OK), null, false)!!.sub)

        val stale = Viz.throttleTile(item("throttle_now", "None", HealthLevel.OK), item("throttle_boot", "None", HealthLevel.OK), true)!!
        assertEquals(Tone.GREY, stale.tone); assertEquals("No data", stale.word)

        assertNull(Viz.throttleTile(null, null, false))
        assertNull(Viz.throttleTile(item("throttle_now", "unavailable", HealthLevel.INFO), null, false))
    }

    @Test fun throttleLinesFoldTheRest() {
        assertEquals(listOf("None"), Viz.throttleLines("None"))
        assertEquals(listOf("Under-voltage", "Throttled"), Viz.throttleLines("Under-voltage, throttled"))
        assertEquals(listOf("Under-voltage", "+2 more"), Viz.throttleLines("Under-voltage, throttled, soft temperature limit"))
    }

    @Test fun throttlingTileSitsAfterTemperatureAndReplacesTheStatusLights() {
        assertEquals(NodeHealthVisual.TEMP, NodeHealthVisual.TILES[0].id)
        assertEquals(NodeHealthVisual.THROTTLE, NodeHealthVisual.TILES[1].id)
        assertEquals(8, NodeHealthVisual.TILES.size)   // even: no empty grid slot

        val o = JSONObject(sample)
        val v = NodeHealthVisual.parse(o)
        val items = NodeHealth.parse(o).items + listOf(item("throttle_now", "None", HealthLevel.OK), item("throttle_boot", "None", HealthLevel.OK))
        assertTrue(NodeHealthVisual.throttleShown(items, v))
        assertFalse(NodeHealthVisual.throttleShown(items, null))
        assertFalse(NodeHealthVisual.throttleShown(items.filter { it.key != "throttle_now" }, v))
        assertFalse(NodeHealthVisual.throttleShown(items.map { if (it.key == "throttle_now") it.copy(level = HealthLevel.INFO, value = "unavailable") else it }, v))

        val groups = items.groupBy { it.group }.map { it.key to it.value }
        val hidden = NodeHealthVisual.throttleIds(items, v)
        val keys = NodeHealthVisual.lights(groups, v, hidden).flatMap { it.second }.map { it.key }
        assertFalse(keys.contains("throttle_now")); assertFalse(keys.contains("throttle_boot"))
        assertTrue(NodeHealthVisual.lights(groups, v).flatMap { it.second }.map { it.key }.containsAll(listOf("throttle_now", "throttle_boot")))
    }

    // ---- INFO items that now carry a level use the traffic-light colours
    @Test fun cpuUseAndVoltageLevelsDriveTheColour() {
        val o = JSONObject("""{"items":[
          {"group":"pi","key":"cpu_use","label":"CPU use","value":"85 %","level":"warn","detail":"busy",
           "metric":{"value":85,"min":0,"max":100,"unit":"%","warn":80,"error":95,"higher_is_worse":true}},
          {"group":"pi","key":"voltage","label":"Core voltage","value":"0.85 V","level":"error","detail":"weak",
           "metric":{"value":0.85,"min":0.8,"max":1.4,"unit":"V","higher_is_worse":true}}]}""")
        val items = NodeHealth.parse(o).items
        assertEquals(Tone.WARN, Viz.toneOf(items[0].level, false))
        assertEquals(Tone.ERROR, Viz.toneOf(items[1].level, false))
        assertEquals(Tone.GREY, Viz.toneOf(items[0].level, true))
        assertEquals(listOf(0.8f, 0.95f), Viz.tickFractions(NodeHealthVisual.parse(o).metric("pi", "cpu_use")!!))
        assertEquals(Tone.GREY, Viz.toneOf(HealthLevel.INFO, false))
    }

    // ---- node screen buttons: blue primary on the node screen only
    @Test fun nodeScreenUsesTheBluePrimaryStyleAndOthersKeepRed() {
        val res = java.io.File("src/main/res")
        val node = java.io.File(res, "layout/activity_node.xml").readText()
        assertFalse(node.contains("@style/Btn.Primary\""))
        assertTrue(node.contains("@style/Btn.NodePrimary"))
        assertTrue(java.io.File(res, "layout/activity_main.xml").readText().contains("@style/Btn.Primary\""))
        val themes = java.io.File(res, "values/themes.xml").readText()
        assertTrue(themes.contains("@drawable/btn_primary"))
        assertTrue(themes.contains("@drawable/node_btn_primary"))
        assertTrue(java.io.File(res, "drawable/btn_primary.xml").readText().contains("@color/red"))
        assertTrue(java.io.File(res, "drawable/node_btn_primary.xml").readText().contains("@color/blue"))
    }

    @Test fun heroSitsAboveActionsAboveHealth() {
        val node = java.io.File("src/main/res/layout/activity_node.xml").readText()
        fun at(id: String) = node.indexOf("android:id=\"@+id/$id\"").also { assertTrue(id, it > 0) }
        val order = listOf("heroTitle", "heroExplain", "updatedText", "launchButton", "healthSection").map { at(it) }
        assertEquals(order.sorted(), order)
        assertFalse(node.contains("minHeight=\"176dp\""))
    }

    private fun lum(c: Int): Double {
        fun ch(x: Int): Double { val s = x / 255.0; return if (s <= 0.03928) s / 12.92 else Math.pow((s + 0.055) / 1.055, 2.4) }
        return 0.2126 * ch((c shr 16) and 255) + 0.7152 * ch((c shr 8) and 255) + 0.0722 * ch(c and 255)
    }
    private fun contrast(a: Int, b: Int): Double { val x = lum(a); val y = lum(b); return (maxOf(x, y) + 0.05) / (minOf(x, y) + 0.05) }
}
