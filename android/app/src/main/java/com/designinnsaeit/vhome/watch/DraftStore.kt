package com.designinnsaeit.vhome.watch

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import org.json.JSONArray
import org.json.JSONObject

/** [key] is the idempotency key: made once with the draft and reused on every resend. */
data class Draft(val key: String, val text: String, val kind: String, val createdAt: Long, val label: String = "")

/**
 * Drafts waiting to reach VNode, in app-private storage (filesDir). The file is PLAINTEXT, not sealed like the
 * pairing token: Android's app sandbox is the only protection. At most 20 drafts / 300 KB of text; when a new
 * draft would exceed either, the oldest are dropped and the caller shows a notice.
 */
class DraftStore(private val file: File) {
    /** [saved] is false when the file could not be written (the draft then exists only in memory). */
    data class Added(val draft: Draft, val dropped: Int, val saved: Boolean = true)

    // In-memory copy so the screen can read drafts on the main thread without touching the file.
    @Volatile private var cache: List<Draft>? = null

    fun all(): List<Draft> = cache ?: synchronized(this) { cache ?: load().also { cache = it } }

    @Synchronized fun add(
        text: String, now: Long = System.currentTimeMillis(), key: String = InboxRules.newKey(),
        kind: String = InboxRules.detectKind(text), label: String = "",
    ): Added {
        val d = Draft(key, text, kind, now, label)
        val (kept, dropped) = enforce(all() + d)
        cache = kept
        return Added(d, dropped, save(kept))
    }

    /** Returns false when the file could not be written. */
    @Synchronized fun remove(key: String): Boolean {
        val kept = all().filter { it.key != key }
        cache = kept
        return save(kept)
    }

    private fun load(): List<Draft> = try {
        val a = JSONArray(file.takeIf { it.exists() }?.readText() ?: "[]")
        (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map {
            Draft(it.optString("key"), it.optString("text"), it.optString("kind"), it.optLong("at"), it.optString("label"))
        }.filter { InboxRules.isValidKey(it.key) }
    } catch (e: Exception) {
        // Damaged file = no drafts, but keep the bytes (one .bak) so nothing is silently lost.
        runCatching { File(file.parentFile, file.name + ".bak").let { bak -> bak.delete(); file.renameTo(bak) } }
        emptyList()
    }

    private fun save(list: List<Draft>): Boolean {
        val a = JSONArray()
        list.forEach { a.put(JSONObject().put("key", it.key).put("text", it.text).put("kind", it.kind).put("at", it.createdAt).put("label", it.label)) }
        val tmp = File(file.parentFile, file.name + ".tmp")
        return try {
            FileOutputStream(tmp).use { it.write(a.toString().toByteArray(Charsets.UTF_8)); it.flush(); it.fd.sync() }
            if (!tmp.renameTo(file)) throw IOException("rename failed")
            true
        } catch (e: IOException) {
            tmp.delete(); false
        }
    }

    companion object {
        /** True when a new draft of [newBytes] fits without dropping any existing draft. */
        fun fits(existing: List<Draft>, newBytes: Int, maxCount: Int = InboxRules.MAX_DRAFTS, maxBytes: Int = InboxRules.MAX_DRAFT_BYTES): Boolean =
            existing.size < maxCount && existing.sumOf { InboxRules.bytes(it.text) } + newBytes <= maxBytes

        /** Oldest first in, oldest dropped first; the newest draft always stays. Returns (kept, number dropped). */
        fun enforce(list: List<Draft>, maxCount: Int = InboxRules.MAX_DRAFTS, maxBytes: Int = InboxRules.MAX_DRAFT_BYTES): Pair<List<Draft>, Int> {
            var kept = list
            while (kept.size > 1 && (kept.size > maxCount || kept.sumOf { InboxRules.bytes(it.text) } > maxBytes)) kept = kept.drop(1)
            return kept to (list.size - kept.size)
        }
    }
}
