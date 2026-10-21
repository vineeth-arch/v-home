package com.designinnsaeit.vhome.watch

import kotlinx.coroutines.flow.Flow
import org.json.JSONObject

// Shared types. Owned by Wave 0; parallel tasks consume these and must not edit this file.

const val PORT = 3001
const val FG_URI = "ssap://com.webos.applicationManager/getForegroundAppInfo"
const val LAUNCH_URI = "ssap://system.launcher/launch"
const val POWER_URI = "ssap://com.webos.service.tvpower/power/getPowerState"
const val DEFAULT_VHOME_ID = "com.designinnsaeit.vhome"
val DEFAULT_HOME_IDS = listOf("com.webos.app.home")

enum class Level { DEBUG, INFO, WARNING, ERROR }

sealed interface Action {
    data class Log(val text: String, val level: Level = Level.INFO) : Action
    data class Launch(val token: Int, val appId: String) : Action
    data class Pause(val reason: String) : Action
}

data class Snapshot(
    val paused: Boolean, val lastApp: String?, val pending: Boolean,
    val redirects: Int, val ok: Int, val failed: Int, val escapes: Int,
    val lastLatencyS: Double?, val lastFailure: String?,
)

class ConfigError(msg: String) : IllegalArgumentException(msg)

data class Config(
    val host: String? = null,
    val clientKey: String? = null,
    val pin: String? = null,
    val vhomeId: String = DEFAULT_VHOME_ID,
    val homeIds: List<String> = DEFAULT_HOME_IDS,
    val doubleHomeEscape: Boolean = false,
    val paused: Boolean = false,
)

class NotPaired(msg: String) : Exception(msg)
class PinMismatch(msg: String) : Exception(msg)

/** One SSAP connection to the TV. Implemented by SsapClient. */
interface TvSession {
    /** SHA-256 hex of the TV's leaf certificate once the TLS handshake is done. */
    val certSha256: String?

    /** Connect, check the pin, register. Returns the client key. */
    suspend fun open(onPrompt: () -> Unit = {}): String

    /** Throws SsapError-style Exception on an error frame or timeout. */
    suspend fun request(uri: String, payload: JSONObject = JSONObject(), timeoutMs: Long = 10_000): JSONObject

    /** Payloads of each subscription message; completes when the connection closes. */
    fun subscribe(uri: String, payload: JSONObject = JSONObject()): Flow<JSONObject>

    fun close()
}
