package com.designinnsaeit.vhome.watch

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.net.NetworkRequest
import android.util.Log

object HomeNetwork {
    /** Idempotent: same request code and intent, so the system replaces the earlier registration. */
    fun register(ctx: Context) {
        try {
            val cm = ctx.getSystemService(ConnectivityManager::class.java)
            val pi = PendingIntent.getBroadcast(
                ctx, 0, Intent(ctx, NetworkReceiver::class.java),
                PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_MUTABLE,
            )
            cm.registerNetworkCallback(wifiRequest(), pi)
        } catch (e: RuntimeException) {
            Log.w("HomeNetwork", "register failed", e)
        }
        WifiJob.arm(ctx) // the durable trigger; the callback above only lives while the app is on screen here
    }

    // The TV is on the LAN: match home Wi-Fi even when the router's internet is down.
    fun wifiRequest(): NetworkRequest = NetworkRequest.Builder()
        .addTransportType(NetworkCapabilities.TRANSPORT_WIFI)
        .removeCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
        .build()

    /** The current Wi-Fi network, so sockets reach the TV even with a VPN or mobile data preferred. */
    @Suppress("DEPRECATION")
    fun wifiNetwork(ctx: Context): Network? {
        val cm = ctx.getSystemService(ConnectivityManager::class.java)
        return cm.allNetworks.firstOrNull {
            cm.getNetworkCapabilities(it)?.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) == true
        }
    }
}

fun applyPairing(c: Config, host: String, key: String, pin: String): Config =
    c.copy(host = host, clientKey = key, pin = pin)
