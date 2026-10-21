package com.designinnsaeit.vhome.watch

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent

object Notify {
    const val CHANNEL = "watch"
    const val ACTION_PAUSE = "com.designinnsaeit.vhome.watch.PAUSE"
    const val ACTION_RESUME = "com.designinnsaeit.vhome.watch.RESUME"
    const val ACTION_RELOAD = "com.designinnsaeit.vhome.watch.RELOAD"
    const val STATUS_PREFS = "vhome_watch_status"
    private const val TAP_ID = 2

    fun ensureChannel(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CHANNEL, ctx.getString(R.string.channel_name), NotificationManager.IMPORTANCE_LOW),
        )
    }

    fun tapToStart(ctx: Context) {
        ensureChannel(ctx)
        val open = PendingIntent.getActivity(
            ctx, 0, Intent(ctx, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val n = Notification.Builder(ctx, CHANNEL)
            .setSmallIcon(R.drawable.ic_stat_watch)
            .setContentTitle(ctx.getString(R.string.tap_to_start))
            .setContentIntent(open)
            .setAutoCancel(true)
            .build()
        ctx.getSystemService(NotificationManager::class.java).notify(TAP_ID, n)
    }
}
