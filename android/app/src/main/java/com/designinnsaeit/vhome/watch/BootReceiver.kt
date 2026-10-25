package com.designinnsaeit.vhome.watch

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        if (Prefs.mode(context) == ControllerMode.STANDALONE && Prefs.load(context).pin != null) startWatcher(context, "boot/update")
        HomeNetwork.register(context)
        WatchdogJob.arm(context)
    }
}

/** Starts the always-on service; if Android refuses a background start, posts Tap to start instead. */
fun startWatcher(ctx: Context, why: String) {
    try {
        ctx.startForegroundService(Intent(ctx, WatcherService::class.java))
    } catch (e: IllegalStateException) {
        EventLog.add(ctx, "Android blocked background start ($why, ${e.javaClass.simpleName}); posted Tap to start")
        Notify.tapToStart(ctx)
    }
}
