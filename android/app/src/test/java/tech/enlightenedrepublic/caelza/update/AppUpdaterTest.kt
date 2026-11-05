package tech.enlightenedrepublic.caelza.update

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import tech.enlightenedrepublic.caelza.runtime.Fetch
import tech.enlightenedrepublic.caelza.runtime.ReleaseInstaller
import java.io.File

/** The app's own update, driven by a canned release feed. */
class AppUpdaterTest {
    @get:Rule
    val tmp = TemporaryFolder()

    private fun asset(name: String) = JSONObject()
        .put("name", name)
        .put("browser_download_url", "https://github.com/Enlightened-Republic/Caelza/releases/download/v0.2.0/$name")

    private fun release(vararg assets: String, tag: String = "v0.2.0", prerelease: Boolean = false, draft: Boolean = false): String =
        JSONObject()
            .put("tag_name", tag)
            .put("prerelease", prerelease)
            .put("draft", draft)
            .put("assets", JSONArray(assets.map { asset(it) }))
            .toString()

    private val signed = arrayOf("caelza-app-0.2.0.apk", "caelza-app-0.2.0.apk.sha256", "caelza-0.2.0-aarch64-linux-android.tar.gz")

    @Test
    fun versionCodeFollowsTheTagRule() {
        assertEquals(1_000L, AppUpdater.versionCode("0.1.0"))
        assertEquals(12_003_004L, AppUpdater.versionCode("v12.3.4"))
        assertNull(AppUpdater.versionCode("0.1.0-rc.1"))
        assertNull(AppUpdater.versionCode("dev-abc12345"))
    }

    @Test
    fun parsePicksTheReleaseSignedApkAndItsChecksum() {
        val u = AppUpdater.parse(release(*signed))!!
        assertEquals("0.2.0", u.version)
        assertEquals(2_000L, u.code)
        assertEquals("caelza-app-0.2.0.apk", u.apkName)
        assertTrue(u.apkUrl.endsWith("/caelza-app-0.2.0.apk"))
        assertTrue(u.shaUrl.endsWith("/caelza-app-0.2.0.apk.sha256"))
    }

    @Test
    fun aDebugSignedApkIsNeverOffered() {
        // It cannot replace a release-signed install; the system installer would refuse it.
        assertNull(AppUpdater.parse(release("caelza-app-0.2.0-debug-signed.apk", "caelza-app-0.2.0-debug-signed.apk.sha256")))
    }

    @Test
    fun noChecksumMeansNoInstall() {
        assertNull(AppUpdater.parse(release("caelza-app-0.2.0.apk")))
    }

    @Test
    fun draftsPrereleasesAndReleasesWithoutAnApkAreSkipped() {
        assertNull(AppUpdater.parse(release(*signed, prerelease = true)))
        assertNull(AppUpdater.parse(release(*signed, draft = true)))
        assertNull(AppUpdater.parse(release("caelza-0.2.0-aarch64-linux-android.tar.gz")))
    }

    @Test
    fun checkOffersOnlyAStrictlyNewerVersion() {
        val feed = Fetch { _, _ -> release(*signed).toByteArray() }
        assertNotNull(AppUpdater(feed).check(installedCode = 1_000))   // 0.1.0 installed, 0.2.0 out
        assertNull(AppUpdater(feed).check(installedCode = 2_000))      // already on it
        assertNull(AppUpdater(feed).check(installedCode = 3_000))      // never a downgrade
        assertNotNull(AppUpdater(feed).check(installedCode = 1))       // a dev build is upgraded by any tag
    }

    private fun feedWithApk(apkBytes: ByteArray, shaLine: String) = object : Fetch {
        override fun get(url: String, accept: String): ByteArray = shaLine.toByteArray()
        override fun download(url: String, accept: String, into: File) = into.writeBytes(apkBytes)
    }

    private val update = AppUpdate("v0.2.0", "0.2.0", 2_000, "caelza-app-0.2.0.apk", "https://x/caelza-app-0.2.0.apk", "https://x/caelza-app-0.2.0.apk.sha256")

    @Test
    fun downloadKeepsAnApkWhoseChecksumHolds() {
        val bytes = "pretend apk".toByteArray()
        val sum = tmp.newFile().apply { writeBytes(bytes) }.let { ReleaseInstaller.sha256(it) }
        val dir = File(tmp.root, "dl")
        val apk = AppUpdater(feedWithApk(bytes, "$sum  caelza-app-0.2.0.apk")).download(update, dir)
        assertTrue(apk.isFile)
        assertEquals(listOf("caelza-app-0.2.0.apk"), dir.list()!!.toList())
    }

    @Test
    fun downloadDeletesAnApkWhoseChecksumFails() {
        val dir = File(tmp.root, "dl")
        val bad = "0".repeat(64)
        assertThrows(IllegalStateException::class.java) {
            AppUpdater(feedWithApk("tampered".toByteArray(), "$bad  caelza-app-0.2.0.apk")).download(update, dir)
        }
        assertFalse(File(dir, "caelza-app-0.2.0.apk").exists())
    }

    @Test
    fun anOlderDownloadIsClearedBeforeTheNewOne() {
        val dir = File(tmp.root, "dl").apply { mkdirs() }
        File(dir, "caelza-app-0.1.0.apk").writeText("old")
        val bytes = "new".toByteArray()
        val sum = tmp.newFile().apply { writeBytes(bytes) }.let { ReleaseInstaller.sha256(it) }
        AppUpdater(feedWithApk(bytes, sum)).download(update, dir)
        assertEquals(listOf("caelza-app-0.2.0.apk"), dir.list()!!.toList())
    }

    @Test
    fun aSignatureFailureIsExplainedInPlainWords() {
        val msg = InstallResultReceiver.failureMessage(android.content.pm.PackageInstaller.STATUS_FAILURE_INCOMPATIBLE, "INSTALL_FAILED_UPDATE_INCOMPATIBLE: signatures do not match")
        assertTrue(msg.contains("different key"))
    }
}
