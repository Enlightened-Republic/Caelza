package tech.enlightenedrepublic.caelza.model

import org.json.JSONArray
import org.json.JSONObject

/**
 * The free local model ladder (vision §3.4), `scripts/model_ladder.py`'s phone
 * branch in Kotlin: which DeepSeek R1 build this phone gets, by RAM. Two
 * tiers come out of a pick: the agent model (the owner's agent when no
 * provider key is configured) and the guide model (Cael, always the 1.5B).
 * The GGUF pins (bartowski's conversions, MIT; sha256 is the Hugging Face LFS
 * oid) are the Python module's, and `export()` is compared against its
 * export in both test suites so the two cannot drift. Honest sizing: the
 * notes say what a 7B on a phone is (tight) and what the 1.5B is for (chat
 * and explanation).
 */
object ModelLadder {
    const val HF = "https://huggingface.co"
    const val GUIDE_TIER = "1.5b"
    const val RUNNER = "llamacpp"
    const val PROVIDER_AGENT = "llamacpp.local"
    const val PROVIDER_GUIDE = "llamacpp.guide"
    /** Where the Runtime's llamacpp provider looks (http://localhost:8080/v1), as `serve.sh` serves it on Termux. */
    const val SERVER_PORT = 8080
    /** `-c 4096` keeps a phone's memory in check. */
    const val CONTEXT = 4096

    data class Gguf(val tier: String, val name: String, val file: String, val repo: String, val sha256: String, val bytes: Long) {
        val url: String get() = "$HF/$repo/resolve/main/$file"
        val mib: Long get() = bytes / 1024 / 1024
    }

    val GGUF: Map<String, Gguf> = linkedMapOf(
        "1.5b" to Gguf(
            "1.5b", "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M", "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
            "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
            "1741e5b2d062b07acf048bf0d2c514dadf2a48f94e2b4aa0cfe069af3838ee2f", 1_117_320_736L,
        ),
        "7b" to Gguf(
            "7b", "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M", "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
            "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
            "731ece8d06dc7eda6f6572997feb9ee1258db0784827e642909d9b565641937b", 4_683_073_184L,
        ),
    )

    data class Pick(val ramMb: Int, val agent: Gguf, val guide: Gguf, val notes: List<String>) {
        val providerAgent: String get() = PROVIDER_AGENT
        val providerGuide: String get() = PROVIDER_GUIDE

        /** What to download, the guide first (as model-setup.sh fetches them); one file when the tiers agree. */
        val files: List<Gguf> get() = if (agent.tier == guide.tier) listOf(agent) else listOf(guide, agent)

        val downloadBytes: Long get() = files.sumOf { it.bytes }
    }

    /** The phone ladder: 6 GB and up gets the 7B for the agent, less gets the 1.5B; Cael always gets the 1.5B. */
    fun pick(ramMb: Int): Pick {
        val notes = mutableListOf<String>()
        val guide = GGUF.getValue(GUIDE_TIER)
        val agent = if (ramMb >= 6 * 1024) {
            notes += "7B Q4 on a phone is tight: keep context short (the server runs with -c 4096)"
            GGUF.getValue("7b")
        } else {
            notes += "<= 5 GB RAM: the 1.5B is for chat and explanation; not reliable for " +
                "multi-step tool calls. Bring a provider key for the agent loop"
            guide
        }
        if (agent.tier != guide.tier) {
            notes += "one llama-server at a time: the agent model is served on :8080; " +
                "Cael shares it unless you run a second server for the guide"
        }
        return Pick(ramMb, agent, guide, notes)
    }

    /** Total RAM in MiB from `ActivityManager.MemoryInfo.totalMem`. */
    fun ramMb(totalBytes: Long): Int = (totalBytes / (1024L * 1024L)).toInt()

    // --- parity with scripts/model_ladder.py ---------------------------------------

    private fun ggufJson(g: Gguf): JSONObject = JSONObject()
        .put("name", g.name).put("file", g.file).put("repo", g.repo).put("sha256", g.sha256).put("bytes", g.bytes)

    /** `Model` as `dataclasses.asdict` prints it. */
    private fun modelJson(g: Gguf): JSONObject = JSONObject()
        .put("tier", g.tier).put("runner", RUNNER).put("name", g.name).put("file", g.file).put("url", g.url)
        .put("sha256", g.sha256).put("bytes", g.bytes).put("pull", "")

    /** `Pick` as `dataclasses.asdict` prints it for `platform = "termux"`. */
    fun pickJson(p: Pick): JSONObject = JSONObject()
        .put("platform", "termux").put("ram_mb", p.ramMb).put("runner", RUNNER)
        .put("agent", modelJson(p.agent)).put("guide", modelJson(p.guide))
        .put("provider_alias_agent", p.providerAgent).put("provider_alias_guide", p.providerGuide)
        .put("notes", JSONArray(p.notes))

    /** The pins and the guide tier, the keys `scripts/android_body_fixtures.py` writes beside the picks. */
    fun export(): JSONObject = JSONObject()
        .put("gguf", JSONObject().also { o -> for ((tier, g) in GGUF) o.put(tier, ggufJson(g)) })
        .put("guide_tier", GUIDE_TIER)
        .put("hf", HF)
}
