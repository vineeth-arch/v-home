package com.designinnsaeit.vhome.watch

import javax.net.SocketFactory
import okhttp3.OkHttpClient

// STUB (Wave 0). Task B3 replaces this file.
object PinTrust {
    fun sha256Hex(der: ByteArray): String = TODO()
    fun client(
        pin: String?, trustNew: Boolean, socketFactory: SocketFactory,
        onCert: (String) -> Unit, pingSeconds: Long = 90,
    ): OkHttpClient = TODO()
}
