package com.designinnsaeit.vhome.watch

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * The pairing with the node: its address, its pinned identity (certificate hash) and this phone's bearer token.
 * The token is sealed with a Keystore key that never leaves the device, so a restored backup or copied
 * prefs file cannot be used (and decrypts to nothing = "not paired").
 */
class NodeStore(ctx: Context) {
    private val prefs = ctx.applicationContext.getSharedPreferences(NAME, Context.MODE_PRIVATE)

    val host: String? get() = prefs.getString("host", null)
    val nodeId: String? get() = prefs.getString("node_id", null)
    val phoneId: String? get() = prefs.getString("phone_id", null)
    val phoneName: String? get() = prefs.getString("phone_name", null)

    fun token(): String? = prefs.getString("token", null)?.let { open(it) }

    fun isPaired(): Boolean = host != null && nodeId != null && token() != null

    fun save(host: String, nodeId: String, phoneId: String, phoneName: String, token: String) {
        val sealed = seal(token)
        prefs.edit().putString("host", host).putString("node_id", nodeId.lowercase())
            .putString("phone_id", phoneId).putString("phone_name", phoneName).putString("token", sealed).apply()
    }

    fun updateHost(host: String) {
        prefs.edit().putString("host", host).apply()
    }

    fun forget() {
        prefs.edit().clear().apply()
        runCatching { KeyStore.getInstance(PROVIDER).apply { load(null) }.deleteEntry(ALIAS) }
    }

    private fun existingKey(): SecretKey? =
        KeyStore.getInstance(PROVIDER).apply { load(null) }.getKey(ALIAS, null) as? SecretKey

    private fun key(): SecretKey {
        existingKey()?.let { return it }
        val spec = KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, PROVIDER).apply { init(spec) }.generateKey()
    }

    /** Base64(iv ‖ ciphertext+tag). */
    private fun seal(plain: String): String {
        val c = Cipher.getInstance(TRANSFORM).apply { init(Cipher.ENCRYPT_MODE, key()) }
        return Base64.encodeToString(c.iv + c.doFinal(plain.toByteArray()), Base64.NO_WRAP)
    }

    private fun open(sealed: String): String? = try {
        val raw = Base64.decode(sealed, Base64.NO_WRAP)
        val c = Cipher.getInstance(TRANSFORM).apply { init(Cipher.DECRYPT_MODE, existingKey() ?: return null, GCMParameterSpec(128, raw, 0, IV_BYTES)) }
        String(c.doFinal(raw, IV_BYTES, raw.size - IV_BYTES))
    } catch (e: Exception) {
        null // key gone (restore, reinstall) or data damaged: treat as not paired
    }

    private companion object {
        const val NAME = "vhome_node"
        const val PROVIDER = "AndroidKeyStore"
        const val ALIAS = "vhome_node_token"
        const val TRANSFORM = "AES/GCM/NoPadding"
        const val IV_BYTES = 12
    }
}
