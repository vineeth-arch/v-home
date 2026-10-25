package com.designinnsaeit.vhome.watch

import java.util.concurrent.TimeUnit
import javax.net.SocketFactory
import kotlinx.coroutines.runBlocking
import okhttp3.Protocol
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import okhttp3.mockwebserver.SocketPolicy
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class InboxClientTest {
    private lateinit var server: MockWebServer
    private lateinit var inbox: InboxClient

    private val job = """{"id":"j1","kind":"text","label":"","status":"queued","created_at":"2026-01-01T00:00:00Z","attempts":0,"retry_safe":false}"""
    private val key = "vh-0123456789abcdef0123456789abcdef"

    @Before fun start() {
        val held = HeldCertificate.Builder().commonName("vnode").addSubjectAlternativeName("localhost").build()
        server = MockWebServer().apply {
            useHttps(HandshakeCertificates.Builder().heldCertificate(held).build().sslSocketFactory(), false)
            protocols = listOf(Protocol.HTTP_1_1)
            start()
        }
        inbox = InboxClient(NodeClient(server.hostName, PinTrust.sha256Hex(held.certificate.encoded), false, SocketFactory.getDefault(), "tok", {}, server.port))
    }

    @After fun stop() = server.shutdown()

    private fun json(body: String, code: Int = 200) = MockResponse().setResponseCode(code).setBody(body)
    private fun nonce() = server.enqueue(json("""{"nonce":"n1"}"""))

    @Test fun submitSendsRawBodyWithHeadersAndIsSentOn201() {
        nonce(); server.enqueue(json("""{"job":$job}""", 201))
        val out = runBlocking { inbox.submit(key, "hello", "text") }
        assertTrue(out is SubmitOutcome.Sent)
        server.takeRequest(1, TimeUnit.SECONDS)!!.let { assertEquals("/v1/nonce", it.path) }
        val r = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/v1/inbox/jobs", r.path)
        assertEquals("hello", r.body.readUtf8())
        assertEquals("text/plain; charset=utf-8", r.getHeader("Content-Type"))
        assertEquals("text", r.getHeader("X-Inbox-Kind"))
        assertEquals(key, r.getHeader("X-Idempotency-Key"))
        assertEquals("n1", r.getHeader("X-VNode-Nonce"))
        assertEquals("Bearer tok", r.getHeader("Authorization"))
    }

    @Test fun duplicate200IsSent() {
        nonce(); server.enqueue(json("""{"job":$job,"duplicate":true}"""))
        assertTrue(runBlocking { inbox.submit(key, "hello", "text") } is SubmitOutcome.Sent)
    }

    @Test fun serverRefusalStaysDraftWithPlainMessageAndNoByKeyLookup() {
        nonce(); server.enqueue(json("""{"error":"queue_full"}""", 429))
        val out = runBlocking { inbox.submit(key, "hello", "text") } as SubmitOutcome.NotDelivered
        assertEquals("VNode queue is full, try later", out.message)
        assertEquals(2, server.requestCount)
    }

    @Test fun ioErrorThenByKey200IsSent() {
        nonce(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(json("""{"job":$job}"""))
        assertTrue(runBlocking { inbox.submit(key, "hello", "text") } is SubmitOutcome.Sent)
        server.takeRequest(1, TimeUnit.SECONDS); server.takeRequest(1, TimeUnit.SECONDS)
        assertEquals("/v1/inbox/by-key/$key", server.takeRequest(1, TimeUnit.SECONDS)!!.path)
        assertEquals(3, server.requestCount) // no automatic resend of the POST
    }

    @Test fun ioErrorThenByKey404IsNotDeliveredButSafe() {
        nonce(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(json("""{"error":"not_found"}""", 404))
        val out = runBlocking { inbox.submit(key, "hello", "text") } as SubmitOutcome.NotDelivered
        assertTrue(out.message, out.message.contains("safe"))
        assertEquals(3, server.requestCount)
    }

    @Test fun ioErrorThenByKey500StaysDraft() {
        nonce(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(json("{}", 500))
        val out = runBlocking { inbox.submit(key, "hello", "text") } as SubmitOutcome.NotDelivered
        assertEquals("Not delivered (HTTP 500)", out.message)
    }

    @Test fun post502ResolvesByKeyAndIsSent() {
        nonce(); server.enqueue(json("{}", 502))
        server.enqueue(json("""{"job":$job}"""))
        assertTrue(runBlocking { inbox.submit(key, "hello", "text") } is SubmitOutcome.Sent)
        assertEquals(3, server.requestCount)
    }

    @Test fun byKeyLookupFailureSaysSendingAgainWillNotDuplicate() {
        nonce(); server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AFTER_REQUEST))
        server.enqueue(MockResponse().setSocketPolicy(SocketPolicy.DISCONNECT_AT_START))
        val out = runBlocking { inbox.submit(key, "hello", "text") } as SubmitOutcome.NotDelivered
        assertEquals("Not confirmed. Sending again will not duplicate it.", out.message)
    }

    @Test fun listAndBrainStatusParse() {
        server.enqueue(json("""{"jobs":[$job],"counts":{"queued":1}}"""))
        val (jobs, counts) = runBlocking { inbox.list(50) }
        assertEquals(1, jobs.size); assertEquals(1, counts!!.queued)
        assertEquals("/v1/inbox/jobs?limit=50", server.takeRequest(1, TimeUnit.SECONDS)!!.path)
        server.enqueue(json("""{"snapshot":null,"stale":true,"worker_stale":true,"queue":{}}"""))
        assertTrue(runBlocking { inbox.brainStatus() }.workerStale)
    }

    @Test fun unparsableRowsAreCountedAndMissingCountsAreNull() {
        server.enqueue(json("""{"jobs":[$job,{"no_id":1},"junk"]}"""))
        val l = runBlocking { inbox.list(50) }
        assertEquals(1, l.jobs.size); assertEquals(2, l.unreadable); assertEquals(null, l.counts)
    }

    @Test fun cancelUsesFreshNonce() {
        nonce(); server.enqueue(json("""{"job":${job.replace("queued", "cancelled")}}"""))
        assertEquals("cancelled", runBlocking { inbox.cancel("j1") }.status)
        server.takeRequest(1, TimeUnit.SECONDS)
        val r = server.takeRequest(1, TimeUnit.SECONDS)!!
        assertEquals("/v1/inbox/jobs/j1/cancel", r.path)
        assertEquals("n1", r.getHeader("X-VNode-Nonce"))
    }
}
