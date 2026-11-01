package tech.enlightenedrepublic.caelza.guide

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import tech.enlightenedrepublic.caelza.body.Repo
import java.io.File

/**
 * Cael's bundled corpus: the asset is guide/corpus.jsonl byte for byte and sized for a
 * phone; the loader upserts every chunk for agents.cael once per corpus version, and a
 * gateway that does not know Cael yet leaves no marker.
 */
class CaelCorpusTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private val asset = File(Repo.root, "android/app/src/main/assets/${CaelCorpus.ASSET}")

    private val sample = """
        {"key": "docs/faq#1", "title": "FAQ", "source": "guide/FAQ.md", "content": "[FAQ]\nA."}
        {"key": "docs/faq#2", "title": "FAQ", "source": "guide/FAQ.md", "content": "[FAQ]\nB."}
        {"key": "docs/book/x#1", "title": "X", "source": "runtime docs/book/src/x.md", "content": "[Runtime docs › X]\nC."}
    """.trimIndent() + "\n"

    @Test
    fun theAssetIsTheRepoCorpusAndFitsAPhone() {
        val text = asset.readText()
        assertEquals("copy guide/corpus.jsonl to android/app/src/main/assets/${CaelCorpus.ASSET}",
            File(Repo.root, "guide/corpus.jsonl").readText(), text)
        val chunks = CaelCorpus.parse(text)
        assertTrue("a real corpus", chunks.size >= 200)
        assertEquals(chunks.size, chunks.map { it.key }.toSet().size)
        assertTrue(chunks.all { it.key.startsWith("docs/") && it.content.startsWith("[") })
        assertTrue("five recalled chunks beside SOUL.md on a 4096-token context", chunks.all { it.content.length <= 900 })
        assertTrue(chunks.any { it.key.startsWith("docs/faq#") })
    }

    @Test
    fun everyChunkIsUpsertedForCaelOncePerCorpusVersion() {
        val posts = mutableListOf<Pair<String, JSONObject>>()
        val corpus = CaelCorpus(tmp.root) { url, body -> posts += url to JSONObject(body); 200 }
        assertNull(corpus.loadedFingerprint())

        val first = corpus.load(sample, 42617)
        assertEquals(Triple(3, 0, false), Triple(first.loaded, first.failed, first.skipped))
        assertEquals(3, posts.size)
        assertTrue(posts.all { it.first == "http://127.0.0.1:42617/api/memory" })
        assertEquals(listOf("docs/faq#1", "docs/faq#2", "docs/book/x#1"), posts.map { it.second.getString("key") })
        assertTrue(posts.all { it.second.getString("agent") == "cael" && it.second.getString("category") == "core" })
        assertEquals("[FAQ]\nA.", posts[0].second.getString("content"))
        assertEquals(CaelCorpus.fingerprint(sample), corpus.loadedFingerprint())
        assertTrue(File(tmp.root, CaelCorpus.MARKER).isFile)

        // The same corpus again: nothing sent.
        val again = corpus.load(sample, 42617)
        assertTrue(again.skipped)
        assertEquals(3, posts.size)

        // A changed corpus is a new fingerprint: it loads.
        // The sample is JSONL: its newlines are the two characters `\n`, so match the encoded text.
        val changed = sample.replace("B.\"", "B, revised.\"")
        assertFalse(CaelCorpus.fingerprint(changed) == CaelCorpus.fingerprint(sample))
        val third = corpus.load(changed, 42617)
        assertEquals(3, third.loaded)
        assertEquals(6, posts.size)
        assertEquals(CaelCorpus.fingerprint(changed), corpus.loadedFingerprint())
    }

    @Test
    fun aGatewayThatDoesNotKnowCaelLeavesNoMarkerAndAFailureIsReported() {
        var calls = 0
        val unknown = CaelCorpus(tmp.root) { _, _ -> calls++; 400 }
        val result = unknown.load(sample, 42617)
        assertEquals(1, calls)
        assertEquals(1, result.failed)
        assertTrue(result.detail, result.detail.contains("does not know agents.cael"))
        assertNull(unknown.loadedFingerprint())

        var n = 0
        val flaky = CaelCorpus(tmp.root) { _, _ -> if (++n == 2) 500 else 200 }
        val partial = flaky.load(sample, 42617)
        assertEquals(Triple(2, 1, "HTTP 500 at docs/faq#2"), Triple(partial.loaded, partial.failed, partial.detail))
        assertNull("a partial load is retried next start", flaky.loadedFingerprint())

        val dead = CaelCorpus(tmp.root) { _, _ -> throw java.net.ConnectException("refused") }
        val gone = dead.load(sample, 42617)
        assertEquals(1, gone.failed)
        assertTrue(gone.detail.contains("stopped answering"))
    }
}
