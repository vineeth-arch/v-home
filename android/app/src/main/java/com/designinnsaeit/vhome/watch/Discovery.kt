package com.designinnsaeit.vhome.watch

import android.content.Context
import android.net.Network

// STUB (Wave 0). Task B2 replaces this file.
object Discovery {
    fun parseSsdpLocation(response: String): String? = TODO()
    suspend fun findTv(
        savedHost: String?, pin: String,
        probe: suspend (String) -> String?, ssdp: suspend () -> List<String>,
    ): String? = TODO()
    fun ssdpSearch(ctx: Context, network: Network): List<String> = TODO()
}
