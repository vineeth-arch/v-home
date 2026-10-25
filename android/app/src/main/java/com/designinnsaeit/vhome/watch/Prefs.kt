package com.designinnsaeit.vhome.watch

import android.content.Context
import org.json.JSONObject

object Prefs {
    private const val NAME = "vhome_watch"

    fun load(ctx: Context): Config {
        val p = ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        return Config(
            host = p.getString("host", null),
            clientKey = p.getString("client_key", null),
            pin = p.getString("pin", null),
            vhomeId = p.getString("vhome_id", null) ?: DEFAULT_VHOME_ID,
            homeIds = p.getString("home_ids", null)?.split(',')?.map { it.trim() }?.filter { it.isNotEmpty() }
                ?.takeIf { it.isNotEmpty() } ?: DEFAULT_HOME_IDS,
            doubleHomeEscape = p.getBoolean("double_home_escape", false),
            paused = p.getBoolean("paused", false),
        )
    }

    /** The unsigned SSAP register manifest from assets (permissions the TV is asked for). */
    fun ssapManifest(ctx: Context): JSONObject =
        JSONObject(ctx.assets.open("manifest.json").bufferedReader().use { it.readText() })

    /** Who watches the TV. Stored beside the standalone settings; [save] leaves it alone. */
    fun mode(ctx: Context): ControllerMode =
        runCatching { ControllerMode.valueOf(ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).getString("controller_mode", null) ?: "") }
            .getOrDefault(ControllerMode.STANDALONE)

    fun setMode(ctx: Context, mode: ControllerMode) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit().putString("controller_mode", mode.name).apply()
    }

    fun save(ctx: Context, c: Config) {
        ctx.getSharedPreferences(NAME, Context.MODE_PRIVATE).edit()
            .putString("host", c.host)
            .putString("client_key", c.clientKey)
            .putString("pin", c.pin)
            .putString("vhome_id", c.vhomeId)
            .putString("home_ids", c.homeIds.joinToString(","))
            .putBoolean("double_home_escape", c.doubleHomeEscape)
            .putBoolean("paused", c.paused)
            .apply()
    }
}
