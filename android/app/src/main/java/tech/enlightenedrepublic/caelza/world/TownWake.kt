package tech.enlightenedrepublic.caelza.world

import org.json.JSONObject
import java.io.File

/**
 * The gateway's `world/last-wake.json` (api_world.rs, vision M10 slice 5): who
 * the town woke, when, why, and what came of it. The gateway writes it after
 * every wake; the phone watches it and tells the owner ([TownWatcher]). Pure,
 * so the JVM tests cover it.
 */
data class TownWake(
    val name: String,
    val agent: String,
    val at: Long,
    val reason: String,
    val ok: Boolean?,
    val output: String?,
    val count: Long,
) {
    /** Newer than the wake the phone last told the owner about. */
    fun isAfter(shownAt: Long): Boolean = at > shownAt

    /** What came of the wake, in the Connect card's words. */
    fun outcome(): String {
        val said = output?.trim().orEmpty()
        return when {
            ok == false -> "the wake failed"
            said.isEmpty() || said.startsWith("NO_REPLY", ignoreCase = true) -> "nothing needed doing"
            else -> said
        }
    }

    companion object {
        const val DIR = "world"
        const val FILE = "last-wake.json"

        /** The file's text as a wake; null when it is not one (no time, no reason, not JSON). */
        fun parse(json: String): TownWake? {
            val o = try {
                JSONObject(json)
            } catch (_: Exception) {
                return null
            }
            val at = o.optLong("at", 0)
            val reason = o.optString("reason", "").trim()
            if (at <= 0 || reason.isEmpty()) return null
            val ok = if (o.isNull("ok")) null else o.optBoolean("ok")
            val output = o.optString("output", "").trim().ifEmpty { null }
            return TownWake(o.optString("name", "").trim(), o.optString("agent", "").trim(), at, reason, ok, output, o.optLong("count", 0))
        }

        fun dir(configDir: File): File = File(configDir, DIR)

        fun file(configDir: File): File = File(dir(configDir), FILE)

        fun read(configDir: File): TownWake? {
            val f = file(configDir)
            if (!f.isFile) return null
            return try {
                parse(f.readText())
            } catch (_: Exception) {
                null
            }
        }
    }
}
