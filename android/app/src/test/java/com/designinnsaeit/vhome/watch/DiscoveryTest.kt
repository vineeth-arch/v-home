package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class DiscoveryTest {
    private val lg = "HTTP/1.1 200 OK\r\nCACHE-CONTROL: max-age=1800\r\n" +
        "LOCATION: http://192.168.29.225:1990/abc/description.xml\r\n" +
        "ST: urn:lge-com:service:webos-second-screen:1\r\n" +
        "USN: uuid:x::urn:lge-com:service:webos-second-screen:1\r\n\r\n"

    @Test fun parsesLgResponse() = assertEquals("192.168.29.225", Discovery.parseSsdpLocation(lg))

    @Test fun ignoresNonLg() {
        val r = "HTTP/1.1 200 OK\r\nLOCATION: http://192.168.29.9:80/d.xml\r\nST: upnp:rootdevice\r\nUSN: uuid:y::upnp:rootdevice\r\n\r\n"
        assertNull(Discovery.parseSsdpLocation(r))
    }

    @Test fun lowercaseHeadersParsed() {
        val r = "HTTP/1.1 200 OK\r\nlocation: http://10.0.0.5:1990/x\r\nst: urn:lge-com:service:webos-second-screen:1\r\n\r\n"
        assertEquals("10.0.0.5", Discovery.parseSsdpLocation(r))
    }

    @Test fun malformedReturnsNull() {
        assertNull(Discovery.parseSsdpLocation(""))
        assertNull(Discovery.parseSsdpLocation("garbage"))
        assertNull(Discovery.parseSsdpLocation("LOCATION: ::bad::\r\nST: webos-second-screen\r\n"))
        assertNull(Discovery.parseSsdpLocation("LOCATION:\r\nST: webos-second-screen\r\n"))
    }

    @Test fun savedHostWinsWhenPinMatches() = runTest {
        var called = false
        val r = Discovery.findTv("192.168.29.224", "AB",
            probe = { if (it == "192.168.29.224") "ab" else null },
            ssdp = { called = true; emptyList() })
        assertEquals("192.168.29.224", r)
        assertEquals(false, called)
    }

    @Test fun findsTvAtNewIpByPin() = runTest {
        val r = Discovery.findTv("192.168.29.224", "aa",
            probe = { if (it == "192.168.29.225") "aa" else null },
            ssdp = { listOf("192.168.29.230", "192.168.29.225") })
        assertEquals("192.168.29.225", r)
    }

    @Test fun noTrustOutsidePairing() = runTest {
        val r = Discovery.findTv("192.168.29.224", "aa",
            probe = { "bb" }, ssdp = { listOf("192.168.29.230", "192.168.29.225") })
        assertNull(r)
    }

    @Test fun ssdpFailureReturnsNull() = runTest {
        val r = Discovery.findTv(null, "aa", probe = { "aa" }, ssdp = { throw RuntimeException("x") })
        assertNull(r)
    }
}
