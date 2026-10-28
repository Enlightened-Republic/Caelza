package tech.enlightenedrepublic.caelza.runtime

import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * Where the Runtime lives inside the app, the way the Body's guard lays it
 * out on a Termux phone (`caelza_body/runtime_guard.py`):
 *
 * ```
 * <home>/runtime/<version>/caelza      one release, unpacked
 * <home>/runtime/current               the version the service runs (a pointer file)
 * <home>/runtime/last-good             what a crash loop falls back to
 * <home>/.caelza/config.toml           the Runtime's config (HOME is <home>)
 * <home>/.local/share/caelza/web/dist  the dashboard, where the gateway looks
 * <home>/logs/daemon.log               the Runtime's output
 * ```
 *
 * The pointers are small files holding a version name, not symlinks: the same
 * on every filesystem and on the JVM the tests run on.
 */
class RuntimeStore(val home: File) {
    val root: File get() = File(home, "runtime")
    val configDir: File get() = File(home, ".caelza")
    val webDist: File get() = File(home, ".local/share/caelza/web/dist")
    val logsDir: File get() = File(home, "logs")

    private val currentFile: File get() = File(root, CURRENT)
    private val lastGoodFile: File get() = File(root, LAST_GOOD)

    fun versionDir(version: String): File = File(root, version)
    fun binary(version: String): File = File(versionDir(version), "caelza")

    /** The version `current` names, whether or not its binary still exists. */
    val current: String? get() = read(currentFile)
    val lastGood: String? get() = read(lastGoodFile)

    /** The binary the service should run, or null when none is installed. */
    val currentBinary: File?
        get() = current?.let { binary(it) }?.takeIf { it.isFile }

    fun installed(): List<String> =
        root.listFiles().orEmpty()
            .filter { it.isDirectory && File(it, "caelza").isFile }
            .map { it.name }
            .sortedWith(VERSION_ORDER)

    fun switch(version: String) {
        require(binary(version).isFile) { "no installed runtime '$version' under $root" }
        point(currentFile, version)
    }

    /** Make `version` current and the last good one (the first install, or one that held). */
    fun promote(version: String) {
        switch(version)
        point(lastGoodFile, version)
    }

    /** Point `current` back at `last-good`; the version, or null when there is nothing to fall back to. */
    fun rollback(): String? {
        val good = lastGood ?: return null
        if (good == current || !binary(good).isFile) return null
        point(currentFile, good)
        return good
    }

    /** Drop versions beyond the newest `keep`, oldest first; never current, last-good or `pin`. */
    fun prune(keep: Int = 3, pin: Set<String> = emptySet()): List<String> {
        val pinned = setOfNotNull(current, lastGood) + pin
        val versions = installed()
        val removable = versions.filter { it !in pinned }.toMutableList()
        val removed = mutableListOf<String>()
        while (versions.size - removed.size > keep && removable.isNotEmpty()) {
            val v = removable.removeAt(0)
            versionDir(v).deleteRecursively()
            removed += v
        }
        return removed
    }

    /** Move an extracted (and probed) release into `runtime/<version>`, swapping a previous copy whole. */
    fun installVersion(version: String, extracted: File): File {
        root.mkdirs()
        val dest = versionDir(version)
        val old = File(root, "$version.old")
        if (old.exists()) old.deleteRecursively()
        if (dest.exists()) check(dest.renameTo(old)) { "could not set aside $dest" }
        if (!extracted.renameTo(dest)) {
            extracted.copyRecursively(dest, overwrite = true)
            extracted.deleteRecursively()
        }
        File(dest, "caelza").setExecutable(true, false)
        if (old.exists()) old.deleteRecursively()
        return dest
    }

    /** The dashboard from a release goes where the gateway looks for it. */
    fun installWebDist(from: File) {
        if (!from.isDirectory) return
        webDist.deleteRecursively()
        webDist.parentFile?.mkdirs()
        from.copyRecursively(webDist, overwrite = true)
    }

    /**
     * A first config when there is none: the gateway on loopback with pairing
     * off, since only this phone's apps can reach it. Everything else is the
     * Runtime's own default; the dashboard's settings and `caelza config set`
     * fill the rest in.
     */
    fun ensureConfig(): File {
        val config = File(configDir, "config.toml")
        if (!config.isFile) {
            configDir.mkdirs()
            config.writeText(DEFAULT_CONFIG)
        }
        return config
    }

    private fun read(pointer: File): String? =
        pointer.takeIf { it.isFile }?.readText()?.trim()?.takeIf { it.isNotEmpty() }

    private fun point(pointer: File, version: String) {
        root.mkdirs()
        val tmp = File(root, ".${pointer.name}.tmp")
        tmp.writeText(version + "\n")
        Files.move(tmp.toPath(), pointer.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }

    companion object {
        const val CURRENT = "current"
        const val LAST_GOOD = "last-good"
        const val GATEWAY_PORT = 42617

        val DEFAULT_CONFIG = """
            |# Written by the Caelza app on first start. The gateway listens on loopback
            |# only; the app's dashboard shell is its client.
            |schema_version = 3
            |
            |[gateway]
            |host = "127.0.0.1"
            |port = $GATEWAY_PORT
            |require_pairing = false
            |""".trimMargin()

        private val SEMVER = Regex("""^(\d+)\.(\d+)\.(\d+)(.*)$""")

        /** 0.10.0 after 0.9.0, not between 0.1.0 and 0.2.0. */
        fun versionKey(version: String): Comparable<*> {
            val m = SEMVER.find(version) ?: return listOf(0, 0, 0, version).joinToString("\u0000")
            return "%08d.%08d.%08d%s".format(m.groupValues[1].toInt(), m.groupValues[2].toInt(), m.groupValues[3].toInt(), m.groupValues[4])
        }

        val VERSION_ORDER: Comparator<String> = compareBy { versionKey(it).toString() }
    }
}
