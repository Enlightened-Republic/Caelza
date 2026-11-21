package tech.enlightenedrepublic.caelza.voice

import org.json.JSONArray
import org.json.JSONObject

/** One of the phone's text-to-speech voices, as the dashboard is told about it. */
data class PhoneVoice(val name: String, val lang: String, val quality: Int, val network: Boolean)

/**
 * The phone's voices as the dashboard's offer wants them (`POST /api/voice/offer`):
 * `[{id, name, lang}]`, the best first (local before online, higher quality
 * first), each name once, at most [MAX]. Pure, so the JVM tests cover it; the
 * Android half is [VoiceBridge].
 */
object VoiceCatalog {
    const val MAX = 200

    fun sorted(voices: Collection<PhoneVoice>): List<PhoneVoice> =
        voices
            .distinctBy { it.name }
            .sortedWith(compareBy<PhoneVoice>({ it.network }, { -it.quality }, { it.lang }, { it.name }))
            .take(MAX)

    /** "en-US · en-us-x-iom-local" reads better than the raw name; online voices say so. */
    fun label(v: PhoneVoice): String = buildString {
        append(v.lang)
        append(" · ")
        append(v.name)
        if (v.network) append(" (online)")
    }

    fun json(voices: Collection<PhoneVoice>): String {
        val out = JSONArray()
        for (v in sorted(voices)) {
            out.put(JSONObject().put("id", v.name).put("name", label(v)).put("lang", v.lang))
        }
        return out.toString()
    }

    /** The voice the dashboard named (its id is the engine's name); blank means the engine's default. */
    fun pick(voices: Collection<PhoneVoice>, id: String?): PhoneVoice? =
        if (id.isNullOrBlank()) null else voices.firstOrNull { it.name == id }
}
