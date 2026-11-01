package tech.enlightenedrepublic.caelza.guide

import org.json.JSONArray
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
 * phone; the loader upserts every chunk for agents.cael once per corpus version, prunes
 * the `docs/` chunks an older corpus left, and a gateway that does not know Cael yet
 * leaves no marker.
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

    private val ok = CaelCorpus.Reply(200, "{\"success\":true}")
    private val scanned = CaelCorpus.Reply(500, "{\"error\":\"Memory store failed: memory write blocked by content scan: send_to_url\"}")

    /** The gateway's memory API as the loader sees it: upsert by key, list, delete; stateful. */
    private class FakeGateway(initial: Set<String>) {
        val entries = initial.toMutableSet()
        val posts = mutableListOf<Pair<String, JSONObject>>()
        val deleted = mutableListOf<String>()
        val bearers = mutableListOf<String?>()
        var listCode = 200

        fun handle(method: String, url: String, body: String?, token: String?): CaelCorpus.Reply {
            bearers += token
            return when (method) {
                "POST" -> {
                    val json = JSONObject(body!!)
                    posts += url to json
                    entries += json.getString("key")
                    CaelCorpus.Reply(200, "{\"success\":true}")
                }
                "GET" -> if (listCode != 200) CaelCorpus.Reply(listCode, "{\"error\":\"boom\"}") else CaelCorpus.Reply(
                    200, JSONObject().put("entries", JSONArray(entries.map { JSONObject().put("key", it).put("category", "core") })).toString(),
                )
                "DELETE" -> {
                    deleted += url
                    val key = java.net.URLDecoder.decode(url.substringAfter("/api/memory/").substringBefore("?"), "UTF-8")
                    entries -= key
                    CaelCorpus.Reply(200, "{\"success\":true,\"deleted\":true}")
                }
                else -> CaelCorpus.Reply(405, "")
            }
        }
    }

    @Test
    fun theAssetIsTheRepoCorpusAndFitsAPhone() {
        val text = asset.readText()
        assertEquals("copy guide/corpus.jsonl to android/app/src/main/assets/${CaelCorpus.ASSET}",
            File(Repo.root, "guide/corpus.jsonl").readText(), text)
        val chunks = CaelCorpus.parse(text)
        assertTrue("a real corpus", chunks.size >= 200)
        assertEquals(chunks.size, chunks.map { it.key }.toSet().size)
        assertTrue(chunks.all { it.key.startsWith(CaelCorpus.KEY_PREFIX) && it.content.startsWith("[") })
        assertTrue("five recalled chunks beside SOUL.md on a 4096-token context", chunks.all { it.content.length <= 900 })
        assertTrue(chunks.any { it.key.startsWith("docs/faq#") })
    }

    @Test
    fun everyChunkIsUpsertedForCaelOncePerCorpusVersionAndStaleDocsArePruned() {
        val gw = FakeGateway(setOf("docs/old#9", "note"))
        val corpus = CaelCorpus(tmp.root, gw::handle)
        assertNull(corpus.loadedFingerprint())

        val first = corpus.load(sample, 42617, "paired-token")
        assertTrue("the app's paired bearer goes on every request, the prune's too", gw.bearers.all { it == "paired-token" })
        assertEquals(Triple(3, 0, false), Triple(first.loaded, first.failed, first.skipped))
        assertEquals(3, gw.posts.size)
        assertTrue(gw.posts.all { it.first == "http://127.0.0.1:42617/api/memory" })
        assertEquals(listOf("docs/faq#1", "docs/faq#2", "docs/book/x#1"), gw.posts.map { it.second.getString("key") })
        assertTrue(gw.posts.all { it.second.getString("agent") == "cael" && it.second.getString("category") == "core" })
        assertEquals("[FAQ]\nA.", gw.posts[0].second.getString("content"))
        assertEquals("the stale docs chunk goes, the owner's note stays", 1, first.pruned)
        assertEquals(listOf("http://127.0.0.1:42617/api/memory/docs%2Fold%239?agent=cael"), gw.deleted)
        assertEquals(setOf("docs/faq#1", "docs/faq#2", "docs/book/x#1", "note"), gw.entries)
        assertTrue(first.detail, first.detail.endsWith("loaded: 3 chunks, 1 stale chunks pruned"))
        assertEquals(CaelCorpus.fingerprint(sample), corpus.loadedFingerprint())
        assertTrue(File(tmp.root, CaelCorpus.MARKER).isFile)

        // The same corpus again: nothing sent.
        val again = corpus.load(sample, 42617)
        assertTrue(again.skipped)
        assertEquals(3, gw.posts.size)

        // A changed corpus is a new fingerprint: it loads; a page that shrank loses its tail.
        // The sample is JSONL: its newlines are the two characters `\n`, so match the encoded text.
        val changed = sample.replace("B.\"", "B, revised.\"").lines().filterNot { it.contains("docs/book/x#1") }.joinToString("\n")
        assertFalse(CaelCorpus.fingerprint(changed) == CaelCorpus.fingerprint(sample))
        val third = corpus.load(changed, 42617)
        assertEquals(2, third.loaded)
        assertEquals(5, gw.posts.size)
        assertEquals(1, third.pruned)
        assertEquals(setOf("docs/faq#1", "docs/faq#2", "note"), gw.entries)
        assertEquals(CaelCorpus.fingerprint(changed), corpus.loadedFingerprint())
    }

    @Test
    fun aGatewayThatDoesNotKnowCaelLeavesNoMarkerAndAFailureIsReported() {
        var calls = 0
        val unknown = CaelCorpus(tmp.root) { _, _, _, _ -> calls++; CaelCorpus.Reply(400, "{\"error\":\"Unknown agent: cael\"}") }
        val result = unknown.load(sample, 42617)
        assertEquals(1, calls)
        assertEquals(1, result.failed)
        assertTrue(result.detail, result.detail.contains("does not know agents.cael"))
        assertNull(unknown.loadedFingerprint())

        var n = 0
        val flaky = CaelCorpus(tmp.root) { method, _, _, _ ->
            assertEquals("no list or delete after a failed store", "POST", method)
            if (++n == 2) CaelCorpus.Reply(500, "{\"error\":\"Memory store failed: boom\"}") else ok
        }
        val partial = flaky.load(sample, 42617)
        assertEquals(Triple(2, 1, "HTTP 500 at docs/faq#2"), Triple(partial.loaded, partial.failed, partial.detail))
        assertNull("a partial load is retried next start", flaky.loadedFingerprint())

        val dead = CaelCorpus(tmp.root) { _, _, _, _ -> throw java.net.ConnectException("refused") }
        val gone = dead.load(sample, 42617)
        assertEquals(1, gone.failed)
        assertTrue(gone.detail.contains("stopped answering"))
    }

    @Test
    fun aGatewayThatKeepsFailingStoresIsGivenUpOnAfterAFewInsteadOfOnePerChunk() {
        val many = (1..8).joinToString("") { "{\"key\": \"docs/p#$it\", \"title\": \"P\", \"source\": \"p.md\", \"content\": \"[P]\\n$it.\"}\n" }
        var posts = 0
        val broken = CaelCorpus(tmp.root) { _, _, _, _ -> posts++; CaelCorpus.Reply(503, "{\"error\":\"busy\"}") }
        val result = broken.load(many, 42617)
        assertEquals(CaelCorpus.MAX_FAILURES, posts)
        assertEquals(CaelCorpus.MAX_FAILURES, result.failed)
        assertTrue(result.detail, result.detail.contains("gave up after ${CaelCorpus.MAX_FAILURES} failures"))
        assertNull(broken.loadedFingerprint())
    }

    @Test
    fun aChunkTheGatewaysContentScanRefusesIsLeftOutAndTheRestStillCounts() {
        // The build drops what the pinned scanner refuses; a newer pin's rule can still refuse a
        // chunk at load time. That is not a failure: the rest goes in, stale chunks are pruned
        // and the marker is written, so the corpus is not retried at every start.
        val gw = FakeGateway(setOf("docs/old#1"))
        var n = 0
        val strict = CaelCorpus(tmp.root) { method, url, body, token -> if (method == "POST" && ++n == 2) scanned else gw.handle(method, url, body, token) }
        val result = strict.load(sample, 42617)
        assertEquals(Triple(2, 0, 1), Triple(result.loaded, result.failed, result.leftOut))
        assertFalse(result.skipped)
        assertEquals(1, result.pruned)
        assertTrue(result.detail, result.detail.contains("2 chunks, 1 left out by the gateway's content scan, 1 stale chunks pruned"))
        assertEquals(CaelCorpus.fingerprint(sample), strict.loadedFingerprint())
    }

    @Test
    fun aPruneThatFailsIsReportedButTheCorpusCountsAsLoaded() {
        val gw = FakeGateway(setOf("docs/old#1")).apply { listCode = 500 }
        val corpus = CaelCorpus(tmp.root, gw::handle)
        val result = corpus.load(sample, 42617)
        assertEquals(Triple(3, 0, 0), Triple(result.loaded, result.failed, result.pruned))
        assertTrue(result.detail, result.detail.contains("prune: could not list Cael's memory (HTTP 500)"))
        assertTrue(gw.deleted.isEmpty())
        assertEquals("the corpus is in; a stale tail only costs recall slots", CaelCorpus.fingerprint(sample), corpus.loadedFingerprint())
    }
}
