package com.designinnsaeit.vhome.watch

// STUB (Wave 0). Task B1 replaces this file.
class Watcher(val vhomeId: String, val homeIds: List<String>, val doubleHomeEscape: Boolean = false) {
    var paused: Boolean = false
    fun onConnected(now: Double): List<Action> = TODO()
    fun onForeground(appId: String?, now: Double): List<Action> = TODO()
    fun onLaunchResult(token: Int, ok: Boolean, now: Double, error: String = ""): List<Action> = TODO()
    fun onTick(now: Double): List<Action> = TODO()
    fun onPowerActive(now: Double): List<Action> = TODO()
    fun nextDeadline(): Double? = TODO()
    fun pause(reason: String = "paused"): List<Action> = TODO()
    fun resume(): List<Action> = TODO()
    fun snapshot(): Snapshot = TODO()
}
