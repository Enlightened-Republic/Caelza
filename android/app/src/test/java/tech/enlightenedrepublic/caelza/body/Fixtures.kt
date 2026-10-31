package tech.enlightenedrepublic.caelza.body

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/** The repo's recordings, found from the module dir Gradle runs the tests in (`android/app`). */
object Repo {
    val root: File by lazy {
        var dir: File = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (true) {
            if (File(dir, "tests/fixtures/playbooks").isDirectory) return@lazy dir
            dir = dir.parentFile ?: error("the repo root (with tests/fixtures/playbooks) is not above ${System.getProperty("user.dir")}")
        }
        @Suppress("UNREACHABLE_CODE")
        dir
    }
    val fixtures: File get() = File(root, "tests/fixtures/playbooks")
    val snapshot: File get() = File(root, "docs/examples/revvl-7-debloat/packages-snapshot.txt")
    val debloatLog: File get() = File(root, "docs/examples/revvl-7-debloat/README.md")
    val appFixtures: File get() = File(root, "android/app/src/test/fixtures")

    fun fixture(name: String): String = File(fixtures, name).readText()
}

/**
 * JSON as one canonical string: keys sorted, every number in its plainest
 * form (`110.0`, whether a Double or the BigDecimal org.json parses it to,
 * reads `110`), so Python's and Kotlin's output compare.
 */
fun canon(v: Any?): String = when (v) {
    null, JSONObject.NULL -> "null"
    is JSONObject -> v.keys().asSequence().sorted().joinToString(",", "{", "}") { JSONObject.quote(it) + ":" + canon(v.get(it)) }
    is JSONArray -> (0 until v.length()).joinToString(",", "[", "]") { canon(v.get(it)) }
    is String -> JSONObject.quote(v)
    is Number -> java.math.BigDecimal(v.toString()).stripTrailingZeros().toPlainString()
    else -> v.toString()
}

/** `tests/fixtures/playbooks/adb.py` in Kotlin: a recorded phone answering each script the tools send. */
open class FakeShell(var available: String? = null) : Shell {
    val calls = mutableListOf<List<String>>()
    var exit = 0

    override fun unavailable(): String? = available

    override fun exec(argv: List<String>, timeoutMs: Long): ExecResult {
        available?.let { throw ShellUnavailable(it) }
        calls += argv
        if (argv.firstOrNull() == "screencap") return ExecResult(0, PNG)
        val script = scriptOf(argv)
        return ExecResult(exit, answer(script).toByteArray())
    }

    protected fun scriptOf(argv: List<String>): String =
        if (argv.size >= 3 && argv[0] == "sh" && argv[1] == "-c") argv[2].removePrefix(BodyShell.SCRIPT_PRELUDE) else argv.joinToString(" ")

    protected open fun answer(script: String): String = when {
        "echo '@@caelza:pkg'; dumpsys package" in script -> Repo.fixture("foreground-detail.txt")
        "pm list packages -i" in script -> Repo.fixture("pm-list-i.txt")
        "pm list packages -3" in script -> packages("-3")
        "pm list packages -d" in script -> packages("-d")
        script.startsWith("pm list packages") -> packages("")
        "@@caelza:identity" in script -> Repo.fixture("health.txt")
        "mCurrentFocus" in script -> Repo.fixture("window-popup.txt")
        "d=$(dumpsys package" in script -> Repo.fixture("suspects.txt")
        else -> "args: $script\n"
    }

    private fun packages(flag: String): String {
        val names = Repo.snapshot.readLines().filter { it.isNotBlank() }.map { it.trim().substringAfterLast("=") }.toMutableSet()
        names += EXTRA
        var list: List<String> = names.sorted()
        if (flag == "-3") list = list.filter { it in THIRD }
        if (flag == "-d") list = listOf("com.tmobile.echolocate")
        return list.joinToString("") { "package:$it\n" } + "@@caelza:end\n"
    }

    companion object {
        val THIRD = setOf(
            "com.govee.home", "com.tailscale.ipn", "com.termux", "com.termux.api",
            "com.example.flashlightpro", "com.cleaner.boost.master",
        )
        val EXTRA = listOf("com.example.flashlightpro", "com.cleaner.boost.master", "com.termux", "com.termux.api")
        val PNG: ByteArray = byteArrayOf(0x89.toByte(), 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A) + "fake".toByteArray()
    }
}
