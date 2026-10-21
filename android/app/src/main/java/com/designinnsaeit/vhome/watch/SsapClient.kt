package com.designinnsaeit.vhome.watch

import java.net.InetSocketAddress
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.atomic.AtomicInteger
import javax.net.SocketFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSocket
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.withContext
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject

/** Kotlin port of companion/vhome_companion/ssap.py. Never logs frames: they can carry the client key. */
class SsapClient(
    val host: String, val clientKey: String?, val pin: String?, val trustNew: Boolean,
    val socketFactory: SocketFactory, val http: OkHttpClient? = null,
    val manifest: JSONObject = JSONObject(), val port: Int = PORT,
) : TvSession {
    @Volatile override var certSha256: String? = null
        private set

    @Volatile private var ws: WebSocket? = null
    @Volatile private var closed = false
    private val ids = AtomicInteger(1)
    private val pending = ConcurrentHashMap<String, CompletableDeferred<JSONObject>>()
    private val subs = ConcurrentHashMap<String, Channel<JSONObject>>()
    private val registration = CompletableDeferred<String>()
    private var onPrompt: () -> Unit = {}

    override suspend fun open(onPrompt: () -> Unit): String {
        this.onPrompt = onPrompt
        val client = http ?: PinTrust.client(pin, trustNew, socketFactory, { certSha256 = it })
        val socket = client.newWebSocket(Request.Builder().url("wss://$host:$port").build(), Listener())
        ws = socket
        val waitMs = if (clientKey != null) 15_000L else 60_000L
        try {
            return withTimeoutOrNull(waitMs) { registration.await() }
                ?: throw NotPaired("timed out waiting for the TV to accept the pairing prompt")
        } catch (e: Throwable) {
            close()
            throw e
        }
    }

    private fun registerFrame(): String {
        val payload = JSONObject()
            .put("forcePairing", false).put("pairingType", "PROMPT")
            .put("manifest", JSONObject(manifest.toString()))
        clientKey?.let { payload.put("client-key", it) }
        return JSONObject().put("type", "register").put("id", "register_0").put("payload", payload).toString()
    }

    private inner class Listener : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            webSocket.send(registerFrame())
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            val msg = try { JSONObject(text) } catch (e: Exception) { return }
            if (registration.isCompleted) dispatch(msg) else handleRegister(msg)
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            webSocket.close(code, null)
            endAll(Exception("connection to the TV closed"))
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            endAll(Exception("connection to the TV lost"))
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            endAll(if (isPinFailure(t)) pinFailure() else Exception("connection to the TV lost (${t.javaClass.simpleName})"))
        }
    }

    private fun isPinFailure(t: Throwable): Boolean {
        var c: Throwable? = t
        while (c != null) {
            if (c is CertificateException && c.message == "pin mismatch") return true
            c = c.cause
        }
        return false
    }

    private fun pinFailure(): Exception =
        if (pin == null) NotPaired("no pinned TV certificate; pair first")
        else PinMismatch("$host presented a different certificate than the one pinned at pair time; refusing to connect")

    private fun handleRegister(msg: JSONObject) {
        when (msg.optString("type")) {
            "registered" -> {
                val key = msg.optJSONObject("payload")?.optString("client-key", "") ?: ""
                if (key.isEmpty()) registration.completeExceptionally(Exception("the TV registered us without a client key"))
                else registration.complete(key)
            }
            "error" -> {
                val err = msg.opt("error")?.toString() ?: "error"
                registration.completeExceptionally(
                    if (err.lowercase().contains("blacklist")) {
                        NotPaired("TV refused registration ($err). The firmware rejects the manifest it was sent; report this with `diag` output.")
                    } else {
                        NotPaired("TV refused registration (401/403 means pairing was declined or the key is no longer valid): $err")
                    },
                )
            }
            "response" -> onPrompt()
        }
    }

    private fun dispatch(msg: JSONObject) {
        val id = msg.optString("id", "")
        val payload = msg.optJSONObject("payload") ?: JSONObject()
        val err: Exception? = when {
            msg.optString("type") == "error" -> Exception(msg.opt("error")?.toString() ?: "error")
            payload.optBoolean("returnValue", true).not() -> Exception(payload.optString("errorText", "request failed"))
            else -> null
        }
        pending[id]?.let { d -> if (err != null) d.completeExceptionally(err) else d.complete(payload); return }
        subs[id]?.let { ch -> if (err != null) ch.close(err) else ch.trySend(payload); return }
    }

    /** Connection is gone: fail the registration and every pending request, complete every subscription. */
    private fun endAll(cause: Exception) {
        registration.completeExceptionally(cause)
        pending.values.forEach { it.completeExceptionally(cause) }
        pending.clear()
        subs.values.forEach { it.close() }
        subs.clear()
    }

    private fun send(frame: JSONObject) {
        val socket = ws
        if (closed || socket == null || !socket.send(frame.toString())) throw Exception("connection to the TV lost")
    }

    override suspend fun request(uri: String, payload: JSONObject, timeoutMs: Long): JSONObject {
        val id = "r${ids.getAndIncrement()}"
        val d = CompletableDeferred<JSONObject>()
        pending[id] = d
        try {
            send(JSONObject().put("type", "request").put("id", id).put("uri", uri).put("payload", payload))
            return withTimeoutOrNull(timeoutMs) { d.await() } ?: throw Exception("timeout")
        } finally {
            pending.remove(id)
        }
    }

    override fun subscribe(uri: String, payload: JSONObject): Flow<JSONObject> = flow {
        val id = "s${ids.getAndIncrement()}"
        val ch = Channel<JSONObject>(Channel.UNLIMITED)
        subs[id] = ch
        try {
            if (closed) return@flow
            send(JSONObject().put("type", "subscribe").put("id", id).put("uri", uri).put("payload", payload))
            for (item in ch) emit(item)
        } finally {
            subs.remove(id)
        }
    }

    override fun close() {
        closed = true
        endAll(Exception("closed"))
        ws?.close(1000, null)
        ws = null
    }
}

/** TLS handshake only; returns the TV's leaf cert SHA-256 hex, or null if unreachable. Never a trust decision. */
suspend fun probePin(host: String, socketFactory: SocketFactory, port: Int = PORT): String? =
    withContext(Dispatchers.IO) {
        var seen: String? = null
        val tm = object : LeafTrustManager() {
            override fun check(leaf: X509Certificate) { seen = PinTrust.sha256Hex(leaf.encoded) }
        }
        val raw = socketFactory.createSocket()
        try {
            raw.connect(InetSocketAddress(host, port), 3000)
            raw.soTimeout = 3000
            val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), SecureRandom()) }
            (ctx.socketFactory.createSocket(raw, host, port, true) as SSLSocket).startHandshake()
            seen
        } catch (e: Exception) {
            null
        } finally {
            try { raw.close() } catch (_: Exception) {}
        }
    }

private val CLIENT_KEY = Regex("(\"client-key\"\\s*:\\s*\")[^\"]*")

fun redact(text: String): String = CLIENT_KEY.replace(text, "$1<redacted>")
