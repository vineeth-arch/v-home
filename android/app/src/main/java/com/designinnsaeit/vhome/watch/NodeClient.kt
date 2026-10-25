package com.designinnsaeit.vhome.watch

import java.io.IOException
import java.security.cert.CertificateException
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory
import javax.net.ssl.SSLPeerUnverifiedException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.Dns
import okhttp3.HttpUrl
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONException
import org.json.JSONObject

data class NodePhone(val id: String, val name: String, val created: String, val isThis: Boolean)
data class TvCandidate(val host: String, val pinned: Boolean)

/**
 * Talks to the V/HOME node (docs/contracts/vnode-api-v1.md). The node's identity is the pinned certificate
 * hash; [trustNew] only exists for the first contact, where the owner then compares the hash by eye.
 * Commands are sent at most once: no retry here, and none at the connection level.
 */
class NodeClient(
    private val host: String, pin: String?, trustNew: Boolean, socketFactory: SocketFactory,
    private val token: String?, onCert: (String) -> Unit = {}, private val port: Int = NODE_PORT,
    dns: Dns = Dns.SYSTEM, // the phone passes the Wi-Fi network's resolver so vnode.local works with a VPN up
) {
    private val http: OkHttpClient = PinTrust.client(pin, trustNew, socketFactory, onCert).newBuilder()
        .dns(dns)
        .readTimeout(15, TimeUnit.SECONDS)
        .callTimeout(20, TimeUnit.SECONDS)
        .build()

    // A command may already have reached the node when the connection drops, so the transport must not replay it.
    private val once: OkHttpClient = http.newBuilder().retryOnConnectionFailure(false).build()

    suspend fun info(): NodeInfo {
        val info = NodeInfo.parse(get("/v1/info"))
        if (info.api != NODE_API) throw NodeException(NodeProblem.PROTOCOL_MISMATCH, "node speaks API ${info.api}")
        return info
    }

    /** Returns phone id and bearer token. The code comes from `vnode pair-phone` on the Pi. */
    suspend fun pair(code: String, name: String): Pair<String, String> {
        val body = JSONObject().put("code", code).put("name", name)
        val o = send(request("/v1/pair").post(body.toBody()).build(), once)
        val id = o.optString("phone_id")
        val tok = o.optString("token")
        if (id.isEmpty() || tok.isEmpty()) throw NodeException(NodeProblem.SERVER, "pairing reply was incomplete")
        return id to tok
    }

    suspend fun status(): NodeStatus = NodeStatus.parse(get("/v1/status"))
    suspend fun device(): DeviceStatus = DeviceStatus.parse(get("/v1/device"))
    suspend fun diagnostics(): String = get("/v1/diagnostics").toString(2)

    suspend fun phones(): List<NodePhone> {
        val arr = get("/v1/phones").optJSONArray("phones") ?: return emptyList()
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }.map {
            NodePhone(it.optString("id"), it.optString("name"), it.optString("created"), it.optBoolean("this"))
        }
    }

    suspend fun tvDiscover(): List<TvCandidate> {
        val arr = get("/v1/tv/discover").optJSONArray("tvs") ?: return emptyList()
        return (0 until arr.length()).mapNotNull { arr.optJSONObject(it) }
            .map { TvCandidate(it.optString("host"), it.optBoolean("pinned")) }
    }

    suspend fun revoke(phoneId: String): CommandResult = command("/v1/phones/$phoneId", method = "DELETE")

    /** Fetch a one-time nonce, then send the command exactly once. DELETE carries the nonce in a header. */
    suspend fun command(path: String, body: JSONObject = JSONObject(), method: String = "POST"): CommandResult {
        val nonce = get("/v1/nonce").optString("nonce")
        if (nonce.isEmpty()) throw NodeException(NodeProblem.SERVER, "the node sent no nonce")
        val req = request(path).apply {
            if (method == "DELETE") delete().header("X-VNode-Nonce", nonce)
            else post(JSONObject(body.toString()).put("nonce", nonce).toBody())
        }.build()
        return CommandResult.parse(send(req, once))
    }

    private suspend fun get(path: String): JSONObject = send(request(path).get().build(), http)

    private fun request(path: String): Request.Builder = Request.Builder().url(buildUrl(host, port, path))
        .header("X-VNode-Api", NODE_API.toString())
        .apply { if (token != null) header("Authorization", "Bearer $token") }

    private fun JSONObject.toBody() = toString().toRequestBody("application/json".toMediaType())

    private suspend fun send(req: Request, client: OkHttpClient): JSONObject = withContext(Dispatchers.IO) {
        try {
            client.newCall(req).execute().use { resp ->
                val text = resp.body?.string().orEmpty()
                if (!resp.isSuccessful) throw httpError(resp.code, text)
                try {
                    JSONObject(text)
                } catch (e: JSONException) {
                    throw NodeException(NodeProblem.SERVER, "the node sent something unreadable")
                }
            }
        } catch (e: NodeException) {
            throw e
        } catch (e: IOException) {
            throw transportError(e)
        }
    }

    companion object {
        /** HttpUrl.Builder takes IPv6 literals and adds the brackets. */
        fun buildUrl(host: String, port: Int, path: String): HttpUrl = HttpUrl.Builder()
            .scheme("https").host(host.trim().removePrefix("[").removeSuffix("]")).port(port)
            .addPathSegments(path.trimStart('/')).build()

        internal fun httpError(code: Int, body: String): NodeException {
            val o = runCatching { JSONObject(body) }.getOrNull()
            val err = o?.optString("error").orEmpty()
            val detail = o?.optString("detail").orEmpty().ifEmpty { "HTTP $code" }
            val problem = when {
                code == 401 -> NodeProblem.UNAUTHORIZED
                code == 409 -> if (err == "busy") NodeProblem.BUSY else NodeProblem.DUPLICATE
                code == 410 -> NodeProblem.EXPIRED
                code == 422 || code == 400 || code == 404 || code == 413 -> NodeProblem.INVALID
                code == 426 -> NodeProblem.PROTOCOL_MISMATCH
                code == 429 -> NodeProblem.RATE_LIMITED
                else -> NodeProblem.SERVER
            }
            return NodeException(problem, detail)
        }

        /** A pin that does not match surfaces from the handshake as a CertificateException somewhere in the cause chain. */
        internal fun transportError(e: IOException): NodeException {
            var t: Throwable? = e
            while (t != null) {
                if (t is CertificateException || t is SSLPeerUnverifiedException)
                    return NodeException(NodeProblem.DIFFERENT_DEVICE, "the certificate is not the pinned one")
                t = t.cause
            }
            return NodeException(NodeProblem.NO_ANSWER, e.javaClass.simpleName + ": " + (e.message ?: ""))
        }
    }
}
