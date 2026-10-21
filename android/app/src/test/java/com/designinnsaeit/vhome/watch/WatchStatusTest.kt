package com.designinnsaeit.vhome.watch

import android.content.SharedPreferences
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Minimal read-only SharedPreferences for the day-rollover rule. */
private class MapPrefs(private val m: Map<String, Any>) : SharedPreferences {
    override fun getAll() = m
    override fun getString(k: String, d: String?) = m[k] as? String ?: d
    override fun getStringSet(k: String, d: MutableSet<String>?) = d
    override fun getInt(k: String, d: Int) = m[k] as? Int ?: d
    override fun getLong(k: String, d: Long) = m[k] as? Long ?: d
    override fun getFloat(k: String, d: Float) = m[k] as? Float ?: d
    override fun getBoolean(k: String, d: Boolean) = m[k] as? Boolean ?: d
    override fun contains(k: String) = m.containsKey(k)
    override fun edit(): SharedPreferences.Editor = throw UnsupportedOperationException()
    override fun registerOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener) {}
    override fun unregisterOnSharedPreferenceChangeListener(l: SharedPreferences.OnSharedPreferenceChangeListener) {}
}

class WatchStatusTest {
    @Test fun explainCoversEveryState() {
        WatchState.values().forEach { assertTrue(it.name, explain(it).isNotBlank() && !explain(it).contains('—')) }
    }

    @Test fun redirectsTodayCountsOnlyToday() {
        val p = MapPrefs(mapOf("count_day" to "2026-10-22", "count" to 12))
        assertEquals(12, WatchStatus.redirectsToday(p, "2026-10-22"))
        assertEquals(0, WatchStatus.redirectsToday(p, "2026-10-23"))
    }

    @Test fun redirectsTodayZeroWhenNeverSet() {
        assertEquals(0, WatchStatus.redirectsToday(MapPrefs(emptyMap()), "2026-10-22"))
    }
}
