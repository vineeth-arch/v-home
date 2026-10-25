package com.designinnsaeit.vhome.watch

import java.io.File
import java.io.FileOutputStream
import java.io.IOException
import org.json.JSONArray
import org.json.JSONObject

/** [key] is the idempotency key: made once with the draft and reused on every resend. */
data class Draft(val key: String, val text: String, val kind: String, val createdAt: Long)

/**
 * Drafts waiting to reach VNode, in app-private storage (filesDir). The file is PLAINTEXT, not sealed like the
 * pairing token: Android's app sandbox is the only protection. At most 20 drafts / 300 KB of text; when a new
 * draft would exceed either, the oldest are dropped and the caller shows a notice.
 */
class DraftStore(private val file: File) {
    /** [saved] is false when the file could not be written (the draft then exists only in memory). */
    data class Added(val draft: Draft, val dropped: Int, val saved: Boolean = true)

    @Synchronized fun all(): List<Draft> = load()

    @Synchronized fun add(text: String, now: Long = System.currentTimeMillis(), key: String = InboxRules.newKey()): Added {
        val d = Draft(key, text, InboxRules.detectKind(text), now)
        val (kept, dropped) = enforce(load() + d)
        return Added(d, dropped, save(kept))
    }

    /** Returns false when the file could not be written. */
    @Synchronized fun remove(key: String): Boolean = save(load().filter { it.key != key })

    private fun load(): List<Draft> = try {
        val a = JSONArray(file.takeIf { it.exists() }?.readText() ?: "[]")
        (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map {
            Draft(it.optString("key"), it.optString("text"), it.optString("kind"), it.optLong("at"))
        }.filter { InboxRules.isValidKey(it.key) }
    } catch (e: Exception) {
        // Damaged file = no drafts, but keep the bytes (one .bak) so nothing is silently lost.
        runCatching { File(file.parentFile, file.name + ".bak").let { bak -> bak.delete(); file.renameTo(bak) } }
        emptyList()
    }

    private fun save(list: List<Draft>): Boolean {
        val a = JSONArray()
        list.forEach { a.put(JSONObject().put("key", it.key).put("text", it.text).put("kind", it.kind).put("at", it.createdAt)) }
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
        /** Oldest first in, oldest dropped first; the newest draft always stays. Returns (kept, number dropped). */
        fun enforce(list: List<Draft>, maxCount: Int = InboxRules.MAX_DRAFTS, maxBytes: Int = InboxRules.MAX_DRAFT_BYTES): Pair<List<Draft>, Int> {
            var kept = list
            while (kept.size > 1 && (kept.size > maxCount || kept.sumOf { InboxRules.bytes(it.text) } > maxBytes)) kept = kept.drop(1)
            return kept to (list.size - kept.size)
        }
    }
}
