package tech.enlightenedrepublic.caelza.voice

import org.json.JSONObject
import java.io.File

/**
 * The agent's chosen voice, as its `voice` tool or the Looks page saved it
 * (vision M10 §10, slice P2c): `agents/<alias>/voice.json` under the Runtime's
 * config dir, in the shape `caelza-tools/src/voice.rs` validates. The engine is
 * `browser` (a PC voice), `phone` (one of this phone's text-to-speech voices,
 * [voice] its name) or `elevenlabs` ([voice] the voice id); [rate] and [pitch]
 * are 1 as the voice comes, bounded as the browsers bound them. Pure, so the
 * JVM tests cover it; the Body speaks it ([tech.enlightenedrepublic.caelza.body.BodyVoice]).
 */
data class VoiceChoice(val engine: String, val voice: String, val name: String?, val rate: Float, val pitch: Float) {
    companion object {
        const val FILE = "voice.json"
        val ENGINES = setOf("browser", "phone", "elevenlabs")
        const val MIN = 0.5f
        const val MAX = 2f

        /** `voice.json`'s text as a choice; null when it is not one (no engine or id, an unknown engine, not JSON). */
        fun parse(json: String): VoiceChoice? {
            val o = try {
                JSONObject(json)
            } catch (_: Exception) {
                return null
            }
            val engine = o.optString("engine", "").trim()
            val voice = o.optString("voice", "").trim()
            if (engine !in ENGINES || voice.isEmpty()) return null
            val name = o.optString("name", "").trim().ifEmpty { null }
            return VoiceChoice(engine, voice, name, number(o, "rate"), number(o, "pitch"))
        }

        private fun number(o: JSONObject, key: String): Float {
            val v = o.optDouble(key, 1.0)
            return (if (v.isNaN()) 1f else v.toFloat()).coerceIn(MIN, MAX)
        }

        fun file(configDir: File, alias: String): File = File(File(File(configDir, "agents"), alias), FILE)

        /** The agent's saved choice, null when it has none (or the file is not a choice). */
        fun read(configDir: File, alias: String): VoiceChoice? {
            val f = file(configDir, alias)
            if (!f.isFile) return null
            return try {
                parse(f.readText())
            } catch (_: Exception) {
                null
            }
        }

        /**
         * The agent that carries the Body: the `[agents.<alias>]` whose `mcp_bundles`
         * names `body`. `main` when it is one of several, and when none does.
         */
        fun bodyAgent(configToml: String): String {
            var section = ""
            val carriers = mutableListOf<String>()
            for (line in configToml.lines()) {
                SECTION.find(line)?.let { section = it.groupValues[1].trim() }
                if (!section.startsWith("agents.")) continue
                val bundles = BUNDLES.find(line)?.groupValues?.get(1) ?: continue
                if (bundles.contains("\"body\"")) carriers += section.removePrefix("agents.").substringBefore('.')
            }
            return if (carriers.isEmpty() || "main" in carriers) "main" else carriers.first()
        }

        private val SECTION = Regex("""^\s*\[([^\]]+)]""")
        private val BUNDLES = Regex("""^\s*mcp_bundles\s*=\s*(\[[^\]]*])""")
    }
}
