package com.designinnsaeit.vhome.watch

import javax.net.SocketFactory
import kotlinx.coroutines.flow.Flow
import okhttp3.OkHttpClient
import org.json.JSONObject

// STUB (Wave 0). Task B3 replaces this file.
class SsapClient(
    val host: String, val clientKey: String?, val pin: String?, val trustNew: Boolean,
    val socketFactory: SocketFactory, val http: OkHttpClient? = null,
) : TvSession {
    override val certSha256: String? get() = TODO()
    override suspend fun open(onPrompt: () -> Unit): String = TODO()
    override suspend fun request(uri: String, payload: JSONObject, timeoutMs: Long): JSONObject = TODO()
    override fun subscribe(uri: String, payload: JSONObject): Flow<JSONObject> = TODO()
    override fun close(): Unit = TODO()
}

/** TLS handshake only; returns the TV's leaf cert SHA-256 hex, or null if unreachable. */
suspend fun probePin(host: String, socketFactory: SocketFactory): String? = TODO()

fun redact(text: String): String = TODO()
