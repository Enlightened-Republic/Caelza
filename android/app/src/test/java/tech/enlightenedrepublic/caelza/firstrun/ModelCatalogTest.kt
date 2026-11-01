package tech.enlightenedrepublic.caelza.firstrun

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import tech.enlightenedrepublic.caelza.body.Repo
import java.io.File

/** The curated catalog the first run's wheels spin: the bundle's file, byte for byte, with a best pick per provider. */
class ModelCatalogTest {
    private val bundle = File(Repo.root, "bundle/models.json")
    private val asset = File(Repo.root, "android/app/src/main/assets/${ModelCatalog.ASSET}")

    @Test
    fun the_asset_is_the_bundles_catalog_byte_for_byte() {
        assertEquals("run python3 scripts/model_catalog.py sync", bundle.readText(), asset.readText())
    }

    @Test
    fun the_catalog_parses_with_a_best_pick_per_provider() {
        val providers = ModelCatalog.parse(asset.readText())
        assertEquals(
            listOf("anthropic", "openai", "gemini", "openrouter", "groq", "deepseek", "mistral", "xai"),
            providers.map { it.id },
        )
        for (p in providers) {
            assertEquals(p.id, 1, p.models.count { it.tag == "best" })
            assertEquals(p.id, p.models.first(), p.best)
            assertTrue(p.id, p.keyPage.startsWith("https://"))
            assertEquals(p.id, p.models.size, p.models.map { it.id }.toSet().size)
            for (m in p.models) assertTrue("${p.id} ${m.id} ${m.tag}", m.tag == null || m.tag in ModelCatalog.TAGS)
        }
        val anthropic = providers.first { it.id == "anthropic" }
        assertEquals("claude-sonnet-5-5", anthropic.best.id)
        assertEquals("Claude Sonnet 5.5 · best pick", anthropic.best.row)
        assertEquals("Claude Opus 5.5", anthropic.models.first { it.id == "claude-opus-5-5" }.row)
        assertEquals("console.anthropic.com/settings/keys", anthropic.where)
        assertEquals("anthropic.default", anthropic.alias)
        assertEquals("sk-ant-", anthropic.keyPrefix)
        assertEquals("", providers.first { it.id == "mistral" }.keyPrefix)
    }

    @Test
    fun the_tags_are_the_catalog_scripts_tags() {
        assertEquals(listOf("best", "fast", "strong", "free"), ModelCatalog.TAGS.keys.toList())
    }
}
