package com.designinnsaeit.vhome.watch

import com.designinnsaeit.vhome.watch.NodeHealthUi.AlertDecision
import com.designinnsaeit.vhome.watch.NodeHealthUi.Colour
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeHealthUiTest {
    private fun item(key: String, level: HealthLevel, group: String = "pi", label: String = key, detail: String = "") =
        HealthItem(group, key, label, "v-$key", level, detail)

    private fun health(vararg items: HealthItem) =
        NodeHealth(items.map { it.level }.maxByOrNull { it.ordinal } ?: HealthLevel.OK, items.size, 0.5, items.toList())

    private val ok = item("temp", HealthLevel.OK)
    private val local = NodeHealthUi.connection(null, false, 3000, false, "10:00")

    @Test fun problemsListErrorsBeforeWarningsKeepingNodeOrder() {
        val items = listOf(
            item("a", HealthLevel.WARN), ok, item("b", HealthLevel.ERROR), item("c", HealthLevel.WARN), item("d", HealthLevel.ERROR),
            item("e", HealthLevel.INFO),
        )
        assertEquals(listOf("b", "d", "a", "c"), NodeHealthUi.problemsOf(items).map { it.key })
    }

    @Test fun summaryForNoOneAndManyProblems() {
        assertEquals("Everything is working", NodeHealthUi.summary(0))
        assertEquals("1 problem", NodeHealthUi.summary(1))
        assertEquals("3 problems", NodeHealthUi.summary(3))
        assertEquals("Everything is working", NodeHealthUi.build(local, health(ok), false).summary)
        val v = NodeHealthUi.build(local, health(item("x", HealthLevel.WARN), item("y", HealthLevel.ERROR)), false)
        assertEquals("2 problems", v.summary)
        assertEquals(HealthLevel.ERROR, v.level)
        assertEquals(HealthLevel.WARN, NodeHealthUi.build(local, health(item("x", HealthLevel.WARN)), false).level)
    }

    @Test fun colourFollowsLevel() {
        assertEquals(Colour.RED, NodeHealthUi.colour(HealthLevel.ERROR, false))
        assertEquals(Colour.AMBER, NodeHealthUi.colour(HealthLevel.WARN, false))
        assertEquals(Colour.NORMAL, NodeHealthUi.colour(HealthLevel.OK, false))
        assertEquals(Colour.NORMAL, NodeHealthUi.colour(HealthLevel.INFO, false))
    }

    @Test fun staleDataIsNeverNormalOrReportedAsWorking() {
        for (l in HealthLevel.values()) assertEquals(Colour.GREY, NodeHealthUi.colour(l, true))
        val node = health(ok, item("x", HealthLevel.WARN))
        val stale = NodeHealthUi.connection(null, true, 30_000, false, "10:00")
        val v = NodeHealthUi.build(stale, node, true)
        assertEquals(listOf("connection"), v.problems.map { it.key })
        assertEquals("1 problem", v.summary)
        assertEquals(HealthLevel.ERROR, v.level)
        assertEquals("Last seen 10:00", NodeHealthUi.valueText(ok, true, "10:00"))
        assertEquals("v-temp", NodeHealthUi.valueText(ok, false, "10:00"))
    }

    @Test fun connectionItemExplainsWhyAndIsOkOtherwise() {
        val c = NodeHealthUi.connection(NodeProblem.NOT_ON_WIFI, false, 0, false, "")
        assertEquals(HealthLevel.ERROR, c.level)
        assertEquals(NodeUi.problemMessage(NodeProblem.NOT_ON_WIFI), c.detail)
        assertEquals(HealthLevel.OK, local.level)
        assertEquals("Updated 3 s ago", local.value)
        assertEquals("v", NodeHealthUi.valueText(local.copy(value = "v"), true, "10:00")) // the phone's own item is never greyed
    }

    @Test fun groupsFollowContractOrderWithPhoneFirst() {
        val items = listOf(
            item("n", HealthLevel.OK, "network"), item("p", HealthLevel.OK, "pi"), item("w", HealthLevel.OK, "watcher"),
            item("t", HealthLevel.OK, "tv"), item("s", HealthLevel.OK, "node"), item("z", HealthLevel.OK, "extra"),
        )
        val v = NodeHealthUi.build(local, health(*items.toTypedArray()), false)
        assertEquals(listOf("phone", "node", "tv", "watcher", "pi", "network", "extra"), v.groups.map { it.first })
        assertEquals(7, v.total)
        assertEquals("Show all 7 indicators", NodeHealthUi.toggleText(7, false))
    }

    @Test fun rowReadsLabelValueProblemDetail() {
        val bad = item("temp", HealthLevel.ERROR, label = "Temperature", detail = "Too hot.")
        assertEquals("Temperature, v-temp, problem: Too hot.", NodeHealthUi.rowDescription(bad, false, "10:00"))
        assertEquals("Temperature, v-temp", NodeHealthUi.rowDescription(ok.copy(label = "Temperature"), false, "10:00"))
        assertEquals("Temperature, Last seen 10:00", NodeHealthUi.rowDescription(bad, true, "10:00"))
    }

    // ---- alerts ----

    @Test fun alertsOnNewErrorSetNamingTheProblems() {
        val h = health(item("throttle_now", HealthLevel.ERROR, label = "Throttling now"), item("wifi_signal", HealthLevel.ERROR, label = "Wi-Fi signal"), item("w", HealthLevel.WARN))
        val d = NodeHealthUi.shouldAlert(emptySet(), h, 0, true) as AlertDecision.Post
        assertEquals("Throttling now · Wi-Fi signal", d.text)
        assertEquals(setOf("throttle_now", "wifi_signal"), d.keys)
    }

    @Test fun noRepeatForTheSameSetButAgainWhenItChanges() {
        val h = health(item("a", HealthLevel.ERROR))
        assertEquals(AlertDecision.None, NodeHealthUi.shouldAlert(setOf("a"), h, 0, true))
        assertTrue(NodeHealthUi.shouldAlert(setOf("a"), health(item("a", HealthLevel.ERROR), item("b", HealthLevel.ERROR)), 0, true) is AlertDecision.Post)
    }

    @Test fun warningsAloneNeverAlertAndClear() {
        assertEquals(AlertDecision.Clear, NodeHealthUi.shouldAlert(setOf("a"), health(item("a", HealthLevel.WARN)), 0, true))
        assertEquals(AlertDecision.Clear, NodeHealthUi.shouldAlert(emptySet(), health(ok), 0, true))
    }

    @Test fun unreachableAlertsAfterTwoRunsOnTheSameWifiOnly() {
        assertEquals(AlertDecision.None, NodeHealthUi.shouldAlert(emptySet(), null, 1, true))
        val d = NodeHealthUi.shouldAlert(emptySet(), null, 2, true)
        assertTrue(d is AlertDecision.Post)
        assertEquals(AlertDecision.None, NodeHealthUi.shouldAlert(emptySet(), null, 5, false))
        assertEquals(AlertDecision.None, NodeHealthUi.shouldAlert((d as AlertDecision.Post).keys, null, 3, true))
    }

    @Test fun answeringAgainClearsTheUnreachableAlert() {
        assertEquals(AlertDecision.Clear, NodeHealthUi.shouldAlert(setOf(NodeHealthUi.UNREACHABLE_KEY), health(ok), 0, true))
        assertNotEquals(AlertDecision.None, NodeHealthUi.shouldAlert(setOf(NodeHealthUi.UNREACHABLE_KEY), health(item("a", HealthLevel.ERROR)), 0, true))
    }
}
