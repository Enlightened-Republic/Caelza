package tech.enlightenedrepublic.caelza.firstrun

import org.json.JSONObject
import java.io.InputStream

/**
 * The curated model catalog (bundle/models.json, bundled as `assets/models.json`
 * byte for byte): the providers most people bring a key for and, for each, the
 * picks Cael pins at the top of the model wheel. The first run's two wheels spin
 * it; the dashboard's /setup spins the same file. `python3 scripts/model_catalog.py
 * sync` refreshes the copy, `ModelCatalogTest` and tests/test_setup_page.py pin it.
 */
object ModelCatalog {
    const val ASSET = "models.json"

    /** The tags a pick can carry, in wheel order (scripts/model_catalog.py TAGS), and Cael's word for each. */
    val TAGS: Map<String, String> = linkedMapOf(
        "best" to "best pick",
        "fast" to "fast and cheap",
        "strong" to "strongest",
        "free" to "free",
    )

    data class Model(val id: String, val label: String, val tag: String?) {
        /** The wheel's row: the label, and the tag when there is one. */
        val row: String get() = if (tag == null) label else "$label · ${TAGS[tag] ?: tag}"
    }

    data class Provider(val id: String, val label: String, val keyPrefix: String, val keyPage: String, val models: List<Model>) {
        /** The alias quickstart creates: `<provider>.default`. */
        val alias: String get() = "$id.default"

        /** Where the model wheel rests. */
        val best: Model get() = models.firstOrNull { it.tag == "best" } ?: models.first()

        /** The key page without its scheme, for a sentence. */
        val where: String get() = keyPage.removePrefix("https://").removePrefix("http://").trimEnd('/')
    }

    fun parse(json: String): List<Provider> {
        val root = JSONObject(json)
        val out = ArrayList<Provider>()
        val providers = root.getJSONArray("providers")
        for (i in 0 until providers.length()) {
            val p = providers.getJSONObject(i)
            val id = p.getString("id")
            val models = ArrayList<Model>()
            val ms = p.getJSONArray("models")
            for (j in 0 until ms.length()) {
                val m = ms.getJSONObject(j)
                models += Model(m.getString("id"), m.getString("label"), m.optString("tag", "").ifEmpty { null })
            }
            require(models.isNotEmpty()) { "provider $id lists no models" }
            out += Provider(id, p.getString("label"), p.optString("key_prefix", ""), p.getString("key_page"), models)
        }
        require(out.isNotEmpty()) { "the catalog lists no providers" }
        return out
    }

    fun load(open: (String) -> InputStream): List<Provider> = parse(open(ASSET).bufferedReader().readText())
}
