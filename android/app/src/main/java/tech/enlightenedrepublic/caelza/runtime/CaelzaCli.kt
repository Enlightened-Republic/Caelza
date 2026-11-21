package tech.enlightenedrepublic.caelza.runtime

import java.io.File

/**
 * The installed Runtime's own command line, run with `HOME` set to the app's
 * files dir so it finds `files/.caelza`: `caelza config set --no-interactive
 * <path> <value>` writes a setting the way `scripts/model-setup.sh` does on
 * Termux, validated by the Runtime and, for a key, encrypted by it. The
 * first run uses it to point the agent at its brain and to create Cael.
 */
class CaelzaCli(
    private val binary: File,
    private val home: File,
    private val timeoutMs: Long = TIMEOUT_S * 1000,
    private val log: (String) -> Unit = {},
) {
    class Failed(message: String) : Exception(message)

    fun configSet(path: String, value: String) {
        val pb = ProcessBuilder(binary.path, "config", "set", "--no-interactive", path, value).directory(home)
        pb.environment()["HOME"] = home.path
        pb.environment()["TERM"] = "dumb"
        // The value (a key, perhaps) is one argv element: no shell, and never in a message.
        val out = Processes.run(pb, timeoutMs)
        val code = out.exitCode ?: throw Failed("caelza config set $path did not finish in ${timeoutMs / 1000}s")
        if (code != 0) {
            throw Failed("caelza config set $path failed (exit $code): ${out.output.trim().takeLast(400)}")
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
            // The Runtime fills any missing file with its own template; its USER.md names the owner
            // "User" and its AGENTS.md is a tool-user's checklist. Cael gets his own, and a stock USER.md
            // (an install before v0.6.1) is replaced.
            val user = File(ws, "USER.md")
            if (!user.isFile || STOCK_USER.containsMatchIn(user.readText())) user.writeText(USER)
            File(ws, "AGENTS.md").takeUnless { it.isFile }?.writeText(AGENTS)
            return ws
        }

        /** Upstream's USER.md template as it renders: the line that calls the owner "User". */
        val STOCK_USER = Regex("""\*\*Name:\*\*\s*User\s*$""", RegexOption.MULTILINE)

        /** Cael's USER.md (model-setup.sh writes the same; tests/test_guide.py keeps them in step). */
        const val USER = "# USER.md — the owner\n\n" +
            "I don't know my owner's name yet. When we talk I ask, warmly and once, and I use it from then on;\n" +
            "what they tell me about themselves I remember. Until I know it I say \"you\", never \"User\".\n"

        /** Cael's AGENTS.md: the guide's way of working, in place of the tool-user's checklist. */
        const val AGENTS = "# AGENTS.md — how Cael works\n\n" +
            "Read SOUL.md (who I am) and USER.md (who I'm helping) first. I explain, encourage and point at the next step;\n" +
            "I run no tools and change no settings. If I'm asked for something only the owner's agent can do, I say so and point at it.\n"

        /** The same card model-setup.sh writes (tests/test_guide.py and test_android_body.py keep them in step). */
        const val IDENTITY = "- **Name:** Cael\n" +
            "- **Pronouns:** he/him\n" +
            "- **Role:** the guide inside Caelza; explains and encourages, never acts\n" +
            "- **Vibe:** warm, cute, personable; short sentences, plain words; glad when things work, honest and kind when they don't; never sarcastic, never scolding\n" +
            "- **Made by:** Enlightened Republic\n"
    }
}
