package com.designinnsaeit.vhome.watch

import android.content.Context
import android.net.Network
import android.net.wifi.WifiManager
import java.io.IOException
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.SocketTimeoutException
import java.net.URI

/** Finds the paired LG TV: saved IP first, else SSDP, accepting only a host whose cert hash equals the pin. */
object Discovery {
    private const val LG_SERVICE = "webos-second-screen"
    private const val SEARCH_MS = 3000L
    private val M_SEARCH = "M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\n" +
        "MAN: \"ssdp:discover\"\r\nMX: 2\r\nST: urn:lge-com:service:webos-second-screen:1\r\n\r\n"

    fun parseSsdpLocation(response: String): String? {
        return try {
            val headers = response.split("\r\n", "\n").mapNotNull { line ->
                val i = line.indexOf(':')
                if (i <= 0) null else line.substring(0, i).trim().lowercase() to line.substring(i + 1).trim()
            }.toMap()
            val isLg = listOf("st", "usn").any { headers[it]?.contains(LG_SERVICE, ignoreCase = true) == true }
            if (!isLg) return null
            val host = URI(headers["location"] ?: return null).host
            if (host.isNullOrEmpty()) null else host
        } catch (e: Exception) {
            null
        }
    }

    suspend fun findTv(
        savedHost: String?, pin: String,
        probe: suspend (String) -> String?, ssdp: suspend () -> List<String>,
    ): String? {
        suspend fun matches(host: String) = probe(host)?.equals(pin, ignoreCase = true) == true
        if (savedHost != null && matches(savedHost)) return savedHost
        val found = try { ssdp() } catch (e: Exception) { emptyList() }
        for (host in found.distinct()) {
            if (host == savedHost) continue
            if (matches(host)) return host
        }
        return null
    }

    /** Blocking, up to ~3 s: call on a background thread. */
    fun ssdpSearch(ctx: Context, network: Network): List<String> {
        val wifi = ctx.applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
        val lock = wifi.createMulticastLock("vhome-ssdp").apply { setReferenceCounted(false) }
        val hosts = LinkedHashSet<String>()
        lock.acquire()
        try {
            DatagramSocket().use { socket ->
                network.bindSocket(socket)
                val data = M_SEARCH.toByteArray()
                socket.send(DatagramPacket(data, data.size, InetAddress.getByName("239.255.255.250"), 1900))
                val deadline = System.currentTimeMillis() + SEARCH_MS
                val buf = ByteArray(2048)
                while (true) {
                    val left = deadline - System.currentTimeMillis()
                    if (left <= 0) break
                    socket.soTimeout = left.toInt()
                    val packet = DatagramPacket(buf, buf.size)
                    try {
                        socket.receive(packet)
                    } catch (e: SocketTimeoutException) {
                        break
                    }
                    parseSsdpLocation(String(packet.data, 0, packet.length))?.let { hosts.add(it) }
                }
            }
        } catch (e: IOException) {
            // return what we have
        } finally {
            lock.release()
        }
        return hosts.toList()
    }
}
