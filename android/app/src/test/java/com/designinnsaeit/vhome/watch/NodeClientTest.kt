package com.designinnsaeit.vhome.watch

import java.util.concurrent.TimeUnit
import javax.net.SocketFactory
import kotlinx.coroutines.runBlocking
import okhttp3.Protocol
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class NodeClientTest {
    private lateinit var server: MockWebServer
    private lateinit var held: HeldCertificate
    private lateinit var pin: String

    @Before fun start() {
        held = HeldCertificate.Builder().commonName("vnode").addSubjectAlternativeName("localhost").build()
        pin = PinTrust.sha256Hex(held.certificate.encoded)
        server = MockWebServer().apply {
            useHttps(HandshakeCertificates.Builder().heldCertificate(held).build().sslSocketFactory(), false)
            protocols = listOf(Protocol.HTTP_1_1)
            start()
        }
    }

    @After fun stop() = server.shutdown()

    private fun client(pin: String?, trustNew: Boolean = false, token: String? = "tok", onCert: (String) -> Unit = {}) =
        NodeClient(server.hostName, pin, trustNew, SocketFactory.getDefault(), token, onCert, server.port)

    private fun json(body: String, code: Int = 200) = MockResponse().setResponseCode(code).setBody(body)

    private fun expectProblem(p: NodeProblem, block: suspend () -> Unit) {
        try {
            runBlocking { block() }
            fail("expected $p")
        } catch (e: NodeException) {
            assertEquals(p, e.problem)
        }
    }

    @Test fun pinnedCertificateWorksAndStatusParses() {
        server.enqueue(json("""{"api":1,"headline":"connected","tv":{"state":"connected","age_s":1.0},"watcher":{"state":"watching"}}"""))
        val s = runBlocking { client(pin).status() }
        assertEquals("connected", s.headline)
        val req = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/v1/status", req.path)
        assertEquals("Bearer tok", req.getHeader("Authorization"))
    }

    @Test fun everyRequestCarriesTheApiHeader() {
        server.enqueue(json("""{"api":1,"node_id":"$pin","name":"vnode","version":"x","capabilities":{}}"""))
        runBlocking { client(pin, token = null).info() }
        val req = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("1", req.getHeader("X-VNode-Api"))
        assertNull(req.getHeader("Authorization"))
    }

    @Test fun wrongPinIsADifferentDevice() {
        server.enqueue(json("{}"))
        expectProblem(NodeProblem.DIFFERENT_DEVICE) { client("0".repeat(64)).status() }
    }

    @Test fun trustNewCapturesTheCertificateHash() {
        server.enqueue(json("""{"api":1,"node_id":"$pin","name":"vnode","version":"x","capabilities":{}}"""))
        var seen: String? = null
        val info = runBlocking { client(null, trustNew = true, token = null) { seen = it }.info() }
        assertEquals(pin, seen)
        assertEquals(pin, info.nodeId)
    }

    @Test fun noPinAndNoTrustRefuses() {
        server.enqueue(json("{}"))
        expectProblem(NodeProblem.DIFFERENT_DEVICE) { client(null).status() }
    }

    @Test fun otherApiVersionIsAMismatch() {
        server.enqueue(json("""{"api":2,"node_id":"$pin"}"""))
        expectProblem(NodeProblem.PROTOCOL_MISMATCH) { client(pin).info() }
    }

    @Test fun httpStatusesMapToProblems() {
        val cases = listOf(
            Triple(401, """{"error":"unauthorized"}""", NodeProblem.UNAUTHORIZED),
            Triple(409, """{"error":"duplicate"}""", NodeProblem.DUPLICATE),
            Triple(409, """{"error":"busy"}""", NodeProblem.BUSY),
            Triple(410, """{"error":"expired"}""", NodeProblem.EXPIRED),
            Triple(422, """{"error":"invalid"}""", NodeProblem.INVALID),
            Triple(426, """{"error":"api_mismatch"}""", NodeProblem.PROTOCOL_MISMATCH),
            Triple(429, """{"error":"rate_limited"}""", NodeProblem.RATE_LIMITED),
            Triple(500, "boom", NodeProblem.SERVER),
            Triple(503, """{"error":"not_ready"}""", NodeProblem.SERVER),
        )
        for ((code, body, problem) in cases) {
            server.enqueue(json(body, code))
            expectProblem(problem) { client(pin).status() }
        }
    }

    @Test fun nothingListeningIsNoAnswer() {
        val port = server.port
        server.shutdown()
        val c = NodeClient("localhost", pin, false, SocketFactory.getDefault(), "tok", port = port)
        expectProblem(NodeProblem.NO_ANSWER) { c.status() }
    }

    @Test fun commandFetchesOneNonceThenPostsOnceWithItInTheBody() {
        server.enqueue(json("""{"nonce":"N123","ttl_s":30}"""))
        server.enqueue(json("""{"outcome":"confirmed","detail":"ok"}"""))
        val r = runBlocking { client(pin).command("/v1/pause", JSONObject().put("minutes", 60)) }
        assertEquals(Outcome.CONFIRMED, r.outcome)
        assertEquals(2, server.requestCount)
        val nonceReq = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("GET", nonceReq.method)
        assertEquals("/v1/nonce", nonceReq.path)
        val post = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("POST", post.method)
        assertEquals("/v1/pause", post.path)
        val body = JSONObject(post.body.readUtf8())
        assertEquals("N123", body.getString("nonce"))
        assertEquals(60, body.getInt("minutes"))
        assertEquals("1", post.getHeader("X-VNode-Api"))
    }

    @Test fun commandDoesNotRetryOnServerError() {
        server.enqueue(json("""{"nonce":"N1","ttl_s":30}"""))
        server.enqueue(json("""{"error":"internal"}""", 500))
        server.enqueue(json("""{"outcome":"confirmed"}"""))   // would be hit by a retry
        expectProblem(NodeProblem.SERVER) { client(pin).command("/v1/resume") }
        assertEquals(2, server.requestCount)
    }

    @Test fun deleteCarriesTheNonceInAHeader() {
        server.enqueue(json("""{"nonce":"N9","ttl_s":30}"""))
        server.enqueue(json("""{"outcome":"confirmed"}"""))
        runBlocking { client(pin).revoke("p_3f9a1c") }
        server.takeRequest(1, TimeUnit.SECONDS)
        val del = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("DELETE", del.method)
        assertEquals("/v1/phones/p_3f9a1c", del.path)
        assertEquals("N9", del.getHeader("X-VNode-Nonce"))
    }

    @Test fun pairReturnsPhoneIdAndToken() {
        server.enqueue(json("""{"phone_id":"p_1","token":"T0K"}"""))
        val (id, token) = runBlocking { client(pin, token = null).pair("K7QM29XD", "Pixel 8") }
        assertEquals("p_1", id)
        assertEquals("T0K", token)
        val body = JSONObject(server.takeRequest(1, TimeUnit.SECONDS)!!.body.readUtf8())
        assertEquals("K7QM29XD", body.getString("code"))
        assertEquals("Pixel 8", body.getString("name"))
    }

    @Test fun ipv6LiteralsGetBrackets() {
        assertEquals("https://[fe80::1]:8443/v1/info", NodeClient.buildUrl("fe80::1", 8443, "/v1/info").toString())
        assertEquals("https://[2001:db8::2]:8443/v1/status", NodeClient.buildUrl("[2001:db8::2]", 8443, "v1/status").toString())
        assertEquals("https://vnode.local:8443/v1/info", NodeClient.buildUrl("vnode.local", 8443, "/v1/info").toString())
        assertNotNull(NodeClient.buildUrl("192.168.29.7", 8443, "/v1/info"))
    }

    @Test fun malformedHostIsInvalidNotACrash() {
        val c = NodeClient("vnode local", null, true, SocketFactory.getDefault(), null)
        expectProblem(NodeProblem.INVALID) { c.info() }
        expectProblem(NodeProblem.INVALID) { NodeClient("vnode.local:8443", null, true, SocketFactory.getDefault(), null).info() }
    }

    @Test fun normalizeHostHandlesCommonPastes() {
        assertEquals("vnode.local", NodeClient.normalizeHost("  vnode.local  "))
        assertEquals("vnode.local", NodeClient.normalizeHost("vnode.local:8443"))
        assertEquals("192.168.1.5", NodeClient.normalizeHost("http://192.168.1.5"))
        assertEquals("192.168.1.5", NodeClient.normalizeHost("HTTPS://192.168.1.5:8443/"))
        assertEquals("[fe80::1]", NodeClient.normalizeHost("[fe80::1]:8443"))
        assertEquals("fe80::8443", NodeClient.normalizeHost("fe80::8443"))
        assertEquals("vnode local", NodeClient.normalizeHost("vnode local"))
    }

    @Test fun phonesList() {
        server.enqueue(json("""{"phones":[{"id":"p_1","name":"Pixel","created":"2026-10-01T00:00:00Z","this":true},{"id":"p_2","name":"Old","created":"x"}]}"""))
        val phones = runBlocking { client(pin).phones() }
        assertEquals(2, phones.size)
        assertTrue(phones[0].isThis)
        assertEquals("p_2", phones[1].id)
    }
}
