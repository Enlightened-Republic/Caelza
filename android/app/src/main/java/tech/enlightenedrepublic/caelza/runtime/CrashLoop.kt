package tech.enlightenedrepublic.caelza.runtime

/** `n` exits inside `windowMs` is a crash loop (the supervisor's rule). */
class CrashLoop(private val n: Int = 3, private val windowMs: Long = 300_000) {
    private val exits = ArrayDeque<Long>()

    fun recordExit(now: Long) {
        exits.addLast(now)
    }

    fun tripped(now: Long): Boolean = exits.count { now - it <= windowMs } >= n

    fun reset() = exits.clear()
}
