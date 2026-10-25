package com.designinnsaeit.vhome.watch

import java.io.IOException
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONObject

/** A read/cancel/retry failed; [message] is already plain wording for the owner. */
class InboxException(message: String) : Exception(message)

/** [unreadable] = rows that failed to parse; the screen says so instead of hiding them. */
data class InboxList(val jobs: List<InboxJob>, val counts: InboxCounts?, val unreadable: Int)

sealed class SubmitOutcome {
    /** Only a 200/201 with a job id, or a by-key lookup that found the job. */
    data class Sent(val job: InboxJob) : SubmitOutcome()
    /** Stays a draft. Sending again is manual and must reuse the draft's key. */
    data class NotDelivered(val message: String) : SubmitOutcome()
}

/**
 * Phone side of the inbox routes (vnode-int-api-v1 "Phone routes"). Reuses [NodeClient]'s pinned OkHttp clients
 * and stored token. Commands are sent once; there is no automatic retry anywhere in here.
 */
class InboxClient(private val node: NodeClient) {
    private class Reply(val code: Int, val body: String) {
        fun json(): JSONObject? = runCatching { JSONObject(body) }.getOrNull()
        val errorCode: String? get() = json()?.optString("error")?.ifEmpty { null }
    }

    suspend fun submit(key: String, text: String, kind: String): SubmitOutcome {
        val nonce = try {
            nonce()
        } catch (e: InboxException) {
            return SubmitOutcome.NotDelivered(e.message ?: "Not delivered")
        }
        val req = node.authedRequest("/v1/inbox/jobs")
            .post(text.toRequestBody("text/plain; charset=utf-8".toMediaType()))
            .header("X-Inbox-Kind", kind).header("X-Idempotency-Key", key).header("X-VNode-Nonce", nonce).build()
        val reply = try {
            exec(node.commandClient, req)
        } catch (e: IOException) {
            // A wrong certificate failed the handshake: nothing was sent. Anything else may have reached VNode.
            if (NodeClient.transportError(e).problem == NodeProblem.DIFFERENT_DEVICE)
                return SubmitOutcome.NotDelivered("This is not the paired VNode")
            return resolveUnknown(key)
        }
        if (reply.code == 200 || reply.code == 201) {
            val job = reply.json()?.optJSONObject("job")?.let { InboxJob.parse(it) }
            return if (job != null) SubmitOutcome.Sent(job) else SubmitOutcome.NotDelivered("VNode sent an unreadable reply")
        }
        if (InboxRules.isAmbiguousServerError(reply.code)) return resolveUnknown(key) // 500/502/504 may have stored it
        return SubmitOutcome.NotDelivered(InboxRules.errorMessage(reply.code, reply.errorCode))
    }

    /** The POST timed out or dropped: ask VNode whether it stored the key, then decide with [InboxRules.byKeyDecision]. */
    private suspend fun resolveUnknown(key: String): SubmitOutcome {
        val r = try {
            exec(node.httpClient, node.authedRequest("/v1/inbox/by-key/$key").get().build())
        } catch (e: IOException) {
            return SubmitOutcome.NotDelivered("Not confirmed. Sending again will not duplicate it.")
        }
        return when (InboxRules.byKeyDecision(r.code)) {
            ByKeyDecision.SENT -> r.json()?.optJSONObject("job")?.let { InboxJob.parse(it) }?.let { SubmitOutcome.Sent(it) }
                ?: SubmitOutcome.NotDelivered("VNode sent an unreadable reply")
            ByKeyDecision.RESEND_SAFE -> SubmitOutcome.NotDelivered("Not delivered, safe to send again")
            ByKeyDecision.KEEP_DRAFT -> SubmitOutcome.NotDelivered(InboxRules.errorMessage(r.code, r.errorCode))
        }
    }

    suspend fun list(limit: Int = 50): InboxList {
        // buildUrl treats its path as segments (it would escape "?"), so the query is added to the built URL.
        val b = node.authedRequest("/v1/inbox/jobs")
        val url = b.build().url.newBuilder().addQueryParameter("limit", limit.toString()).build()
        val o = call(node.httpClient, b.url(url).get().build()).json() ?: throw InboxException("VNode sent an unreadable reply")
        val arr = o.optJSONArray("jobs")
        val rows = (0 until (arr?.length() ?: 0)).map { arr!!.optJSONObject(it)?.let { r -> InboxJob.parse(r) } }
        return InboxList(rows.filterNotNull(), InboxCounts.parse(o.optJSONObject("counts")), rows.count { it == null })
    }

    suspend fun brainStatus(): BrainStatus = BrainStatus.parse(getJson("/v1/inbox/brain-status"))

    suspend fun cancel(id: String): InboxJob = act(id, "cancel")
    suspend fun retry(id: String): InboxJob = act(id, "retry")

    private suspend fun act(id: String, verb: String): InboxJob {
        val nonce = nonce()
        val req = node.authedRequest("/v1/inbox/jobs/$id/$verb").post(ByteArray(0).toRequestBody(null))
            .header("X-VNode-Nonce", nonce).build()
        val r = call(node.commandClient, req)
        return r.json()?.optJSONObject("job")?.let { InboxJob.parse(it) } ?: throw InboxException("VNode sent an unreadable reply")
    }

    private suspend fun nonce(): String {
        val n = getJson("/v1/nonce").optString("nonce")
        if (n.isEmpty()) throw InboxException("VNode sent no nonce")
        return n
    }

    private suspend fun getJson(path: String): JSONObject =
        call(node.httpClient, node.authedRequest(path).get().build()).json() ?: throw InboxException("VNode sent an unreadable reply")

    /** Non-2xx and transport errors become [InboxException] with plain wording. */
    private suspend fun call(client: OkHttpClient, req: Request): Reply {
        val r = try {
            exec(client, req)
        } catch (e: IOException) {
            throw InboxException(NodeUi.problemMessage(NodeClient.transportError(e).problem))
        }
        if (r.code !in 200..299) throw InboxException(InboxRules.errorMessage(r.code, r.errorCode))
        return r
    }

    // enqueue + cancel-on-cancellation: a cancelled scope aborts the call instead of throwing after a completed POST.
    private suspend fun exec(client: OkHttpClient, req: Request): Reply = suspendCancellableCoroutine { cont ->
        val call = client.newCall(req)
        cont.invokeOnCancellation { call.cancel() }
        call.enqueue(object : Callback {
            override fun onFailure(call: Call, e: IOException) { if (cont.isActive) cont.resumeWithException(e) }
            override fun onResponse(call: Call, response: Response) {
                val r = try {
                    response.use { Reply(it.code, it.body?.string().orEmpty()) }
                } catch (e: IOException) {
                    if (cont.isActive) cont.resumeWithException(e); return
                }
                if (cont.isActive) cont.resume(r)
            }
        })
    }
}
