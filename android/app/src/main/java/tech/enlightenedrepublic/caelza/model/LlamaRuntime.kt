package tech.enlightenedrepublic.caelza.model

import tech.enlightenedrepublic.caelza.runtime.ReleaseInstaller
import java.io.File
import java.nio.file.Files
import java.nio.file.StandardCopyOption

/**
 * The llama.cpp build the app runs: the project's own prebuilt Android arm64
 * release (`llama-<tag>-bin-android-arm64.tar.gz`, `llama-server` with its
 * shared libraries beside it, RPATH `$ORIGIN`, CPU variants picked at run
 * time). Pinned by tag and sha256 and moved deliberately, the way the GGUFs
 * are; the sha256 was taken from the archive on 2026-10-31.
 */
data class LlamaPin(val tag: String, val sha256: String, val bytes: Long) {
    val asset: String get() = "llama-$tag-bin-android-arm64.tar.gz"
    val url: String get() = "https://github.com/ggml-org/llama.cpp/releases/download/$tag/$asset"

    companion object {
        val CURRENT = LlamaPin("b11960", "77d9f19fad41d6d8efbc29bcc1c1ab60a605018564cfc32203892eb1973ba4b9", 78_624_092L)
    }
}

/**
 * Where the local model server lives inside the app, beside the Runtime's
 * own versions and with the same pointer file:
 *
 * ```
 * <home>/runtime/llama/<tag>/llama-server   one release, unpacked (its .so files beside it)
 * <home>/runtime/llama/current              the tag the service runs (a pointer file)
 * ```
 *
 * `command()` is `serve.sh`'s line on Termux: `llama-server -m <gguf> --host
 * 127.0.0.1 --port 8080 -c 4096 --threads N`.
 */
class LlamaRuntime(val home: File) {
    val root: File get() = File(home, "runtime/llama")
    private val currentFile: File get() = File(root, "current")

    val current: String? get() = currentFile.takeIf { it.isFile }?.readText()?.trim()?.takeIf { it.isNotEmpty() }

    fun server(tag: String): File = File(root, "$tag/llama-server")

    /** The server the service should run, or null when none is installed. */
    val currentServer: File? get() = current?.let { server(it) }?.takeIf { it.isFile }

    val installed: Boolean get() = currentServer != null

    /** Download the pinned build (verified against its pinned sha256), unpack it, point `current` at it. */
    fun install(downloader: Downloader, progress: (Long, Long) -> Unit = { _, _ -> }, pin: LlamaPin = LlamaPin.CURRENT): File {
        if (server(pin.tag).isFile) {
            point(pin.tag)
            progress(pin.bytes, pin.bytes)
            return server(pin.tag)
        }
        val work = File(home, "tmp/llama-install-${System.nanoTime()}").apply { mkdirs() }
        try {
            val archive = File(work, pin.asset)
            VerifiedDownload.fetch(pin.url, pin.sha256, pin.bytes, archive, downloader, progress)
            val extracted = ReleaseInstaller.unpack(archive, File(work, "x"), BINARY)
            root.mkdirs()
            val dest = File(root, pin.tag)
            if (dest.exists()) dest.deleteRecursively()
            if (!extracted.renameTo(dest)) {
                extracted.copyRecursively(dest, overwrite = true)
                extracted.deleteRecursively()
            }
            File(dest, BINARY).setExecutable(true, false)
            point(pin.tag)
            return server(pin.tag)
        } finally {
            work.deleteRecursively()
        }
    }

    /** Drop every installed tag but `current`. */
    fun prune(): List<String> {
        val keep = current
        val removed = mutableListOf<String>()
        root.listFiles()?.filter { it.isDirectory && it.name != keep }?.forEach {
            it.deleteRecursively()
            removed += it.name
        }
        return removed
    }

    private fun point(tag: String) {
        root.mkdirs()
        val tmp = File(root, ".current.tmp")
        tmp.writeText(tag + "\n")
        Files.move(tmp.toPath(), currentFile.toPath(), StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE)
    }

    companion object {
        const val BINARY = "llama-server"

        /** `serve.sh`'s command line. */
        fun command(server: File, model: File, port: Int = ModelLadder.SERVER_PORT, ctx: Int = ModelLadder.CONTEXT, threads: Int = cpuThreads()): List<String> =
            listOf(server.path, "-m", model.path, "--host", "127.0.0.1", "--port", port.toString(), "-c", ctx.toString(), "--threads", threads.toString())

        /** `nproc`, as serve.sh uses it. */
        fun cpuThreads(): Int = Runtime.getRuntime().availableProcessors().coerceAtLeast(1)
    }
}
