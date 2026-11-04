package tech.enlightenedrepublic.caelza.update

import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInstaller
import android.net.Uri
import android.os.Build
import android.provider.Settings
import org.json.JSONObject
import tech.enlightenedrepublic.caelza.runtime.Fetch
import tech.enlightenedrepublic.caelza.runtime.HttpFetch
import tech.enlightenedrepublic.caelza.runtime.ReleaseInstaller
import java.io.File

/** A newer APK on the release feed. `code` is the versionCode its tag gives (scripts/app_version.py). */
data class AppUpdate(val tag: String, val version: String, val code: Long, val apkName: String, val apkUrl: String, val shaUrl: String)

/**
 * The app's own update (the Runtime updates through the guard; this is the APK around it).
 *
 * Android never updates a sideloaded app by itself, so the app asks the release feed: the
 * latest release's `caelza-app-<version>.apk` with its `.sha256`. A newer one is downloaded,
 * checked against the published checksum, and handed to the system installer, which asks
 * the owner to confirm and refuses an APK signed by a different key. That last check is
 * why only release-signed assets (no `-debug-signed`) are ever offered: a debug-signed APK
 * cannot replace a release-signed one and the installer would fail it.
 */
class AppUpdater(
    private val fetch: Fetch = HttpFetch(),
    private val repo: String = ReleaseInstaller.DEFAULT_REPO,
) {
    /** The newest release's APK when it is newer than `installedCode`, else null. Throws on a network failure. */
    fun check(installedCode: Long): AppUpdate? {
        val url = "${ReleaseInstaller.RELEASES_API}/$repo/releases/latest"
        val update = parse(String(fetch.get(url, "application/vnd.github+json"))) ?: return null
        return update.takeIf { it.code > installedCode }
    }

    /** Download the APK into `dir` and verify its checksum; the file is deleted if it does not verify. */
    fun download(update: AppUpdate, dir: File): File {
        dir.mkdirs()
        dir.listFiles()?.forEach { it.delete() }  // an older download is never installed by mistake
        val apk = File(dir, update.apkName)
        try {
            fetch.download(update.apkUrl, "application/octet-stream", apk)
            ReleaseInstaller.verifySha256(apk, String(fetch.get(update.shaUrl, "application/octet-stream")))
        } catch (e: Exception) {
            apk.delete()
            throw e
        }
        return apk
    }

    companion object {
        const val CHECK_INTERVAL_MS = 6L * 60 * 60 * 1000
        private val APK = Regex("""^caelza-app-(\d+\.\d+\.\d+)\.apk$""")
        private val TAG = Regex("""^v?(\d+)\.(\d+)\.(\d+)$""")

        /** versionCode = major × 1 000 000 + minor × 1 000 + patch, the rule in scripts/app_version.py. */
        fun versionCode(version: String): Long? {
            val m = TAG.matchEntire(version.trim()) ?: return null
            val (major, minor, patch) = m.destructured
            return major.toLong() * 1_000_000 + minor.toLong() * 1_000 + patch.toLong()
        }

        /**
         * The release-signed APK and its checksum from one release's JSON, or null when the release
         * has none (an Android leg that was skipped, a debug-signed-only release, a pre-release tag).
         */
        fun parse(json: String): AppUpdate? {
            val data = JSONObject(json)
            val tag = data.optString("tag_name", "")
            if (data.optBoolean("draft", false) || data.optBoolean("prerelease", false)) return null
            val assets = data.optJSONArray("assets") ?: return null
            val byName = LinkedHashMap<String, String>()
            for (i in 0 until assets.length()) {
                val a = assets.getJSONObject(i)
                byName[a.optString("name", "")] = a.optString("browser_download_url", "")
            }
            val apk = byName.keys.firstOrNull { APK.matches(it) } ?: return null
            val version = APK.matchEntire(apk)!!.groupValues[1]
            val code = versionCode(version) ?: return null
            val apkUrl = byName[apk]?.takeIf { it.startsWith("https://") } ?: return null
            val shaUrl = byName["$apk.sha256"]?.takeIf { it.startsWith("https://") } ?: return null  // no checksum, no install
            return AppUpdate(tag, version, code, apk, apkUrl, shaUrl)
        }

        /** True when Android lets this app install packages; false sends the owner to the setting first. */
        fun canInstall(context: Context): Boolean =
            Build.VERSION.SDK_INT < Build.VERSION_CODES.O || context.packageManager.canRequestPackageInstalls()

        /** The system page where the owner allows Caelza to install updates ("install unknown apps"). */
        fun allowInstallsIntent(context: Context): Intent =
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:${context.packageName}"))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)

        /** Stream the verified APK to a PackageInstaller session and commit it; the result comes to [InstallResultReceiver]. */
        fun install(context: Context, apk: File) {
            val installer = context.packageManager.packageInstaller
            val params = PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL)
            val id = installer.createSession(params)
            installer.openSession(id).use { session ->
                apk.inputStream().use { input ->
                    session.openWrite("caelza.apk", 0, apk.length()).use { out ->
                        input.copyTo(out)
                        session.fsync(out)
                    }
                }
                val intent = Intent(context, InstallResultReceiver::class.java).setPackage(context.packageName)
                val flags = PendingIntent.FLAG_UPDATE_CURRENT or
                    (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) PendingIntent.FLAG_MUTABLE else 0)
                session.commit(PendingIntent.getBroadcast(context, id, intent, flags).intentSender)
            }
        }
    }
}
