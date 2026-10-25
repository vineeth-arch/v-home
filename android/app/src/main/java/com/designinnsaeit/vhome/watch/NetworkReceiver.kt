package com.designinnsaeit.vhome.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.util.Log

class NetworkReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Prefs.load(context).pin == null) return // not paired yet
        if (Prefs.mode(context) == ControllerMode.VNODE) return // the node watches; this phone stays quiet
        EventLog.add(context, "Wi-Fi joined: starting watcher")
        try {
            context.startForegroundService(Intent(context, WatcherService::class.java))
        } catch (e: IllegalStateException) {
            // Includes ForegroundServiceStartNotAllowedException (Android 12+, a subclass).
            Log.w("NetworkReceiver", "cannot start service from background", e)
            EventLog.add(context, "Android blocked background start (${e.javaClass.simpleName}); posted Tap to start")
            Notify.tapToStart(context)
        }
    }
}
