package tech.enlightenedrepublic.caelza.runtime

import java.io.File
import java.util.concurrent.TimeUnit

/**
 * The installed Runtime's own command line, run with `HOME` set to the app's
 * files dir so it finds `files/.caelza`: `caelza config set --no-interactive
 * <path> <value>` writes a setting the way `scripts/model-setup.sh` does on
 * Termux, validated by the Runtime and, for a key, encrypted by it. The
 * first run uses it to point the agent at its brain and to create Cael.
 */
class CaelzaCli(private val binary: File, private val home: File, private val log: (String) -> Unit = {}) {
    class Failed(message: String) : Exception(message)

    fun configSet(path: String, value: String) {
        val pb = ProcessBuilder(binary.path, "config", "set", "--no-interactive", path, value)
            .directory(home)
            .redirectErrorStream(true)
        pb.environment()["HOME"] = home.path
        pb.environment()["TERM"] = "dumb"
        val proc = pb.start()
        proc.outputStream.close()
        val out = proc.inputStream.bufferedReader().readText()
        if (!proc.waitFor(TIMEOUT_S, TimeUnit.SECONDS)) {
            proc.destroyForcibly()
            throw Failed("caelza config set $path did not finish in ${TIMEOUT_S}s")
        }
        if (proc.exitValue() != 0) {
            throw Failed("caelza config set $path failed (exit ${proc.exitValue()}): ${out.trim().takeLast(400)}")
        }
        log("set $path")
    }

    /** Every entry in order; the first failure stops the rest and carries the Runtime's own message. */
    fun configure(entries: List<Pair<String, String>>) {
        for ((path, value) in entries) configSet(path, value)
    }

    companion object {
        const val TIMEOUT_S = 60L

        /**
         * Cael's workspace (`<config dir>/agents/cael/workspace`): `SOUL.md` from
         * the bundled `guide/cael.system.md`, `IDENTITY.md` the card
         * `scripts/model-setup.sh` writes. A file the owner already has is left alone.
         */
        fun writeCaelPersona(configDir: File, soul: String): File {
            val ws = File(configDir, "agents/cael/workspace").apply { mkdirs() }
            File(ws, "SOUL.md").takeUnless { it.isFile }?.writeText(soul)
            File(ws, "IDENTITY.md").takeUnless { it.isFile }?.writeText(IDENTITY)
            return ws
        }

        /** The same card model-setup.sh writes (tests/test_guide.py and test_android_body.py keep them in step). */
        const val IDENTITY = "- **Name:** Cael\n" +
            "- **Pronouns:** he/him\n" +
            "- **Role:** the guide inside Caelza; explains and encourages, never acts\n" +
            "- **Vibe:** warm, cute, personable; short sentences, plain words; glad when things work, honest and kind when they don't; never sarcastic, never scolding\n" +
            "- **Made by:** Enlightened Republic\n"
    }
}
