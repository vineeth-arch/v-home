package com.designinnsaeit.vhome.watch

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NodeContractsTest {
    private val statusJson = """
        {"api":1,"node":{"id":"abc","version":"0.2.0+abc1234","uptime_s":5231,"service":"ok"},"headline":"connected",
         "tv":{"state":"connected","host":"192.168.29.225","paired":true,"power":"Active","foreground":"com.webos.app.livetv",
               "age_s":2.1,"last_error":null,"pairing":{"state":"idle","detail":""}},
         "watcher":{"state":"watching","enabled":true,"paused":false,"pause_reason":null,"paused_until":null,"redirects":12,
                    "ok":12,"failed":0,"last_latency_s":1.84,"last_failure":null,"last_redirect_age_s":310.0}}
    """

    @Test fun statusSample() {
        val s = NodeStatus.parse(JSONObject(statusJson))
        assertEquals("connected", s.headline)
        assertEquals("0.2.0+abc1234", s.nodeVersion)
        assertEquals(5231L, s.nodeUptimeS)
        assertEquals("192.168.29.225", s.tvHost)
        assertEquals(2.1, s.tvAgeS!!, 0.001)
        assertNull(s.tvLastError)
        assertEquals("idle", s.pairingState)
        assertEquals("watching", s.watcherState)
        assertEquals(12, s.redirects)
        assertEquals(1.84, s.lastLatencyS!!, 0.001)
        assertNull(s.pausedUntil)
        assertNull(s.lastFailure)
    }

    @Test fun statusWithNullsAndPause() {
        val o = JSONObject(statusJson)
        o.getJSONObject("tv").put("age_s", JSONObject.NULL).put("host", JSONObject.NULL).put("state", "unreachable")
        o.getJSONObject("watcher").put("state", "user_paused").put("paused", true)
            .put("paused_until", "2026-10-25T21:04:00Z").put("last_latency_s", JSONObject.NULL)
        val s = NodeStatus.parse(o)
        assertNull(s.tvAgeS)
        assertNull(s.tvHost)
        assertEquals("unreachable", s.tvState)
        assertTrue(s.paused)
        assertEquals("2026-10-25T21:04:00Z", s.pausedUntil)
        assertNull(s.lastLatencyS)
        assertEquals(1_792_962_240_000L, NodeUi.parseInstantMs(s.pausedUntil))
    }

    @Test fun emptyStatusDoesNotClaimAnything() {
        val s = NodeStatus.parse(JSONObject("{}"))
        assertEquals("unknown", s.headline)
        assertEquals("unknown", s.tvState)
        assertEquals("not_ready", s.watcherState)
    }

    @Test fun deviceSample() {
        val d = DeviceStatus.parse(JSONObject("""
            {"temp_c":45.1,"throttled":"0x0","mem_used_mb":61,"mem_total_mb":426,"disk_free_mb":820,"uptime_s":9000,
             "wifi":{"dbm":-69,"bars":2},
             "leds":{"enabled":true,"brightness":3,"bars":2,"thermal_off":false,"age_s":4.0},"age_s":0.0}
        """))
        assertEquals(45.1, d.tempC!!, 0.001)
        assertEquals("0x0", d.throttled)
        assertEquals(426, d.memTotalMb)
        assertEquals(-69, d.wifiDbm)
        assertEquals(2, d.wifiBars)
        assertTrue(d.ledsAvailable)
        assertEquals(3, d.ledsBrightness)
    }

    @Test fun deviceWithoutLedsOrWifi() {
        val d = DeviceStatus.parse(JSONObject("""
            {"temp_c":null,"throttled":null,"mem_used_mb":1,"mem_total_mb":2,"disk_free_mb":3,"uptime_s":4,"wifi":null,"leds":null}
        """))
        assertNull(d.tempC)
        assertNull(d.throttled)
        assertNull(d.wifiDbm)
        assertFalse(d.ledsAvailable)
    }

    @Test fun infoSample() {
        val i = NodeInfo.parse(JSONObject("""
            {"api":1,"node_id":"${"a".repeat(64)}","name":"vnode","version":"0.2.0+abc1234",
             "capabilities":{"launch":"supported","timer":"unavailable","power_on_launch":"unverified"}}
        """))
        assertEquals(NODE_API, i.api)
        assertEquals(64, i.nodeId.length)
        assertEquals("unavailable", i.capabilities["timer"])
        assertEquals(3, i.capabilities.size)
    }

    @Test fun commandResults() {
        assertEquals(Outcome.CONFIRMED, CommandResult.parse(JSONObject("""{"outcome":"confirmed"}""")).outcome)
        assertEquals(Outcome.UNKNOWN, CommandResult.parse(JSONObject("""{"outcome":"weird"}""")).outcome)
        assertEquals("busy", CommandResult.parse(JSONObject("""{"outcome":"failed","detail":"busy"}""")).detail)
    }
}
