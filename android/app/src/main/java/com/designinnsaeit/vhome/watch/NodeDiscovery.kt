package com.designinnsaeit.vhome.watch

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.os.Handler
import android.os.Looper
import java.net.Inet4Address
import kotlinx.coroutines.delay

/** A node found on the network. Only a candidate: trust comes from the pinned fingerprint, never from mDNS. */
data class NodeCandidate(val name: String, val host: String, val port: Int, val idPrefix: String?)

/** Finds `_vhome._tcp` services. Callers get results on the main thread; stop() when the screen pauses. */
class NodeDiscovery(ctx: Context) {
    private val nsd = ctx.applicationContext.getSystemService(NsdManager::class.java)
    private val main = Handler(Looper.getMainLooper())
    private val queue = ArrayDeque<NsdServiceInfo>()
    private var resolving = false
    private var listener: NsdManager.DiscoveryListener? = null
    private var onFound: ((NodeCandidate) -> Unit)? = null

    fun start(found: (NodeCandidate) -> Unit) {
        if (listener != null) return
        onFound = found
        val l = object : NsdManager.DiscoveryListener {
            override fun onDiscoveryStarted(serviceType: String) {}
            override fun onDiscoveryStopped(serviceType: String) {}
            override fun onStartDiscoveryFailed(serviceType: String, errorCode: Int) { main.post { listener = null } }
            override fun onStopDiscoveryFailed(serviceType: String, errorCode: Int) {}
            override fun onServiceLost(serviceInfo: NsdServiceInfo) {}
            override fun onServiceFound(serviceInfo: NsdServiceInfo) { main.post { enqueue(serviceInfo) } }
        }
        listener = l
        runCatching { nsd.discoverServices(NODE_SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, l) }
            .onFailure { listener = null }
    }

    fun stop() {
        val l = listener ?: return
        listener = null
        onFound = null
        queue.clear()
        runCatching { nsd.stopServiceDiscovery(l) }
    }

    /** One short scan, for re-finding a node whose address changed. */
    suspend fun scan(ms: Long = 4_000): List<NodeCandidate> {
        val got = mutableListOf<NodeCandidate>()
        start { got += it }
        delay(ms)
        stop()
        return got.distinctBy { it.host to it.port }
    }

    // The legacy resolver allows one resolve at a time; queue them.
    private fun enqueue(info: NsdServiceInfo) {
        queue.addLast(info)
        next()
    }

    @Suppress("DEPRECATION")
    private fun next() {
        if (resolving) return
        val info = queue.removeFirstOrNull() ?: return
        resolving = true
        val done = { resolving = false; next() }
        try {
            nsd.resolveService(info, object : NsdManager.ResolveListener {
                override fun onResolveFailed(serviceInfo: NsdServiceInfo, errorCode: Int) { main.post(done) }
                override fun onServiceResolved(serviceInfo: NsdServiceInfo) {
                    main.post {
                        candidate(serviceInfo)?.let { onFound?.invoke(it) }
                        done()
                    }
                }
            })
        } catch (e: RuntimeException) {
            resolving = false
        }
    }

    @Suppress("DEPRECATION")
    private fun candidate(i: NsdServiceInfo): NodeCandidate? {
        val addr = i.host ?: return null
        if (addr.isLinkLocalAddress && addr !is Inet4Address) return null // needs a scope id OkHttp cannot use
        val host = (addr.hostAddress ?: return null).substringBefore('%').trimStart('/')
        val id = i.attributes?.get("id")?.let { String(it) }?.takeIf { it.isNotEmpty() }
        return NodeCandidate(i.serviceName, host, i.port.takeIf { it > 0 } ?: NODE_PORT, id)
    }
}
