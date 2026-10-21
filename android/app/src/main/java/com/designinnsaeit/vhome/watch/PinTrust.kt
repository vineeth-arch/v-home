package com.designinnsaeit.vhome.watch

import java.net.Socket
import java.security.MessageDigest
import java.security.SecureRandom
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLEngine
import javax.net.ssl.X509ExtendedTrustManager
import okhttp3.OkHttpClient

/**
 * The TV's certificate comes from LG's own CA and is addressed by IP, so identity is the SHA-256 of
 * the leaf certificate (pinned at pair time), checked during the handshake, before any frame is sent.
 */
object PinTrust {
    fun sha256Hex(der: ByteArray): String =
        MessageDigest.getInstance("SHA-256").digest(der).joinToString("") { "%02x".format(it) }

    fun client(
        pin: String?, trustNew: Boolean, socketFactory: SocketFactory,
        onCert: (String) -> Unit, pingSeconds: Long = 90,
    ): OkHttpClient {
        val tm = PinTrustManager(pin, trustNew, onCert)
        val ctx = SSLContext.getInstance("TLS").apply { init(null, arrayOf(tm), SecureRandom()) }
        return OkHttpClient.Builder()
            .socketFactory(socketFactory)
            .sslSocketFactory(ctx.socketFactory, tm)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(10, TimeUnit.SECONDS)
            .pingInterval(pingSeconds, TimeUnit.SECONDS)
            .build()
    }
}

/** Extended so the JDK does not layer its own algorithm-constraint checks on top of the pin. */
internal abstract class LeafTrustManager : X509ExtendedTrustManager() {
    abstract fun check(leaf: X509Certificate)

    override fun checkServerTrusted(chain: Array<X509Certificate>?, authType: String?) = checkChain(chain)
    override fun checkServerTrusted(chain: Array<X509Certificate>?, authType: String?, socket: Socket?) = checkChain(chain)
    override fun checkServerTrusted(chain: Array<X509Certificate>?, authType: String?, engine: SSLEngine?) = checkChain(chain)
    override fun checkClientTrusted(chain: Array<X509Certificate>?, authType: String?) = throw CertificateException("no client auth")
    override fun checkClientTrusted(chain: Array<X509Certificate>?, authType: String?, socket: Socket?) = throw CertificateException("no client auth")
    override fun checkClientTrusted(chain: Array<X509Certificate>?, authType: String?, engine: SSLEngine?) = throw CertificateException("no client auth")
    override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

    private fun checkChain(chain: Array<X509Certificate>?) {
        val leaf = chain?.firstOrNull() ?: throw CertificateException("the TV presented no certificate")
        check(leaf)
    }
}

internal class PinTrustManager(
    private val pin: String?, private val trustNew: Boolean, private val onCert: (String) -> Unit,
) : LeafTrustManager() {
    override fun check(leaf: X509Certificate) {
        val hash = PinTrust.sha256Hex(leaf.encoded)
        onCert(hash)
        val ok = if (pin != null) {
            MessageDigest.isEqual(pin.lowercase().toByteArray(), hash.toByteArray())
        } else trustNew
        if (!ok) throw CertificateException("pin mismatch")
    }
}
