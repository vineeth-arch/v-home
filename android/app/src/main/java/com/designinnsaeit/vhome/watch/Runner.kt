package com.designinnsaeit.vhome.watch

// STUB (Wave 0). Task C replaces this file.
class Runner(
    val watcher: Watcher, val session: TvSession,
    val persistPaused: (Boolean) -> Unit, val clock: () -> Double,
) {
    suspend fun session(): Unit = TODO()
}

/** Reconnect delay in seconds: 5 * 2^attempt, capped at 300, +-20% jitter. */
fun backoff(attempt: Int, rand: () -> Double = Math::random): Double = TODO()
