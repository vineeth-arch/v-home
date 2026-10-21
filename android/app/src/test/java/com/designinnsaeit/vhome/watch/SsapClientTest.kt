package com.designinnsaeit.vhome.watch

import java.util.concurrent.CopyOnWriteArrayList
import javax.net.SocketFactory
import kotlinx.coroutines.flow.take
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class SsapClientTest {
    private val held = HeldCertificate.Builder().addSubjectAlternativeName("localhost").build()
    private val goodPin = PinTrust.sha256Hex(held.certificate.encoded)
    private val manifest = JSONObject("""{"manifestVersion":1,"permissions":["LAUNCH"]}""")
    private val server = MockWebServer()
    private val received = CopyOnWriteArrayList<String>()
    private var client: SsapClient? = null

    @Before fun setUp() {
        val certs = HandshakeCertificates.Builder().heldCertificate(held).build()
        server.useHttps(certs.sslSocketFactory(), false)
        server.start()
    }

    @After fun tearDown() {
        client?.close()
        server.shutdown()
    }

    /** Scripts the TV side: every client frame is recorded, then handed to [handler]. */
    private fun tv(handler: (WebSocket, JSONObject) -> Unit) {
        server.enqueue(MockResponse().withWebSocketUpgrade(object : WebSocketListener() {
            override fun onClosing(webSocket: WebSocket, code: Int, reason: String) { webSocket.close(code, null) }
            override fun onMessage(webSocket: WebSocket, text: String) {
                received.add(text)
                handler(webSocket, JSONObject(text))
            }
        }))
    }

    private fun registered(ws: WebSocket, key: String = "KEY1") {
        ws.send("""{"type":"registered","id":"register_0","payload":{"client-key":"$key"}}""")
    }

    private fun registerOnly(ws: WebSocket, msg: JSONObject) {
        if (msg.getString("type") == "register") registered(ws)
    }

    private fun ssap(pin: String?, trustNew: Boolean = false, clientKey: String? = null) =
        SsapClient("localhost", clientKey, pin, trustNew, SocketFactory.getDefault(),
            manifest = manifest, port = server.port).also { client = it }

    @Test fun matchingPinConnects() = runBlocking {
        tv(::registerOnly)
        assertEquals("KEY1", ssap(goodPin).open())
    }

    @Test fun mismatchedPinRejected() = runBlocking {
        tv(::registerOnly)
        try {
            ssap("0".repeat(64)).open()
            fail("expected PinMismatch")
        } catch (e: PinMismatch) {
        }
        assertTrue(received.isEmpty())
        assertEquals(0, server.requestCount)
    }

    @Test fun noPinNoTrustNewRejected() = runBlocking {
        tv(::registerOnly)
        try {
            ssap(null, trustNew = false).open()
            fail("expected NotPaired")
        } catch (e: NotPaired) {
        }
        assertTrue(received.isEmpty())
    }

    @Test fun trustNewRecordsPin() = runBlocking {
        tv(::registerOnly)
        val c = ssap(null, trustNew = true)
        c.open()
        assertEquals(PinTrust.sha256Hex(held.certificate.encoded), c.certSha256)
    }

    @Test fun registerReturnsClientKey() = runBlocking {
        tv { ws, m -> if (m.getString("type") == "register") registered(ws, "NEWKEY") }
        assertEquals("NEWKEY", ssap(goodPin, clientKey = "OLDKEY").open())
        val p = JSONObject(received[0]).getJSONObject("payload")
        assertEquals("OLDKEY", p.getString("client-key"))
    }

    @Test fun registerSendsNoSignedBlock() = runBlocking {
        tv(::registerOnly)
        ssap(goodPin).open()
        val m = JSONObject(received[0])
        assertEquals("register", m.getString("type"))
        assertEquals("register_0", m.getString("id"))
        val p = m.getJSONObject("payload")
        assertFalse(p.getBoolean("forcePairing"))
        assertEquals("PROMPT", p.getString("pairingType"))
        assertEquals(manifest.toString(), p.getJSONObject("manifest").toString())
        assertFalse(p.has("client-key"))
        assertFalse(received[0].contains("signed"))
    }

    @Test fun registerErrorBlacklistMessage() = runBlocking {
        tv { ws, _ ->
            ws.send("""{"type":"error","id":"register_0","error":"403 Pairing rejected: blacklisted certificate detected"}""")
        }
        try {
            ssap(goodPin).open()
            fail("expected NotPaired")
        } catch (e: NotPaired) {
            assertTrue(e.message!!.startsWith("TV refused registration (403 Pairing rejected"))
            assertTrue(e.message!!.contains("rejects the manifest"))
        }
    }

    @Test fun subscribeDeliversPayloads() = runBlocking {
        tv { ws, m ->
            when (m.getString("type")) {
                "register" -> registered(ws)
                "subscribe" -> {
                    val id = m.getString("id")
                    ws.send("""{"type":"response","id":"$id","payload":{"n":1}}""")
                    ws.send("not json")
                    ws.send("""{"type":"response","id":"$id","payload":{"n":2}}""")
                }
            }
        }
        val c = ssap(goodPin)
        c.open()
        val got = c.subscribe("ssap://x").take(2).toList()
        assertEquals(listOf(1, 2), got.map { it.getInt("n") })
        assertEquals("ssap://x", JSONObject(received[1]).getString("uri"))
    }

    @Test fun requestReturnsPayload() = runBlocking {
        tv { ws, m ->
            when (m.getString("type")) {
                "register" -> registered(ws)
                "request" -> ws.send("""{"type":"response","id":"${m.getString("id")}","payload":{"returnValue":true,"x":7}}""")
            }
        }
        val c = ssap(goodPin)
        c.open()
        assertEquals(7, c.request("ssap://y", JSONObject().put("a", 1)).getInt("x"))
        val sent = JSONObject(received[1])
        assertEquals("ssap://y", sent.getString("uri"))
        assertEquals(1, sent.getJSONObject("payload").getInt("a"))
    }

    @Test fun requestTimesOut() = runBlocking {
        tv(::registerOnly)
        val c = ssap(goodPin)
        c.open()
        try {
            c.request("ssap://z", timeoutMs = 300)
            fail("expected timeout")
        } catch (e: Exception) {
            assertEquals("timeout", e.message)
        }
    }

    @Test fun probePinReturnsHash() = runBlocking {
        assertEquals(goodPin, probePin("localhost", SocketFactory.getDefault(), server.port))
    }

    @Test fun redactsClientKey() {
        val out = redact("""{"payload":{"client-key" : "SECRET123","a":"b"}}""")
        assertFalse(out.contains("SECRET123"))
        assertTrue(out.contains("<redacted>"))
        assertTrue(out.contains(""""a":"b""""))
    }
}
