package tech.enlightenedrepublic.caelza.logs

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import tech.enlightenedrepublic.caelza.runtime.RuntimeStore
import java.io.File
import java.time.Instant

/**
 * The bug report: tails cut at a line, secrets blanked wherever they hide, every log
 * the app writes in the report under the name the service gives it.
 */
class BugReportTest {
    @get:Rule
    val tmp = TemporaryFolder()

    @Test
    fun theTailIsWholeLinesAndSaysWhatItSkipped() {
        val file = tmp.newFile("daemon.log")
        val lines = (1..20).map { "line %02d ".format(it) + "x".repeat(40) }   // 48 chars + newline each
        file.writeText(lines.joinToString("\n") + "\n")
        val whole = BugReport.tail(file, 10_000)
        assertEquals(file.readText(), whole)

        val tail = BugReport.tail(file, 200)
        val body = tail.lines()
        assertTrue(tail, body[0].startsWith("… ") && body[0].endsWith("earlier not shown"))
        assertEquals("the cut lands on a line boundary", "line 17 " + "x".repeat(40), body[1])
        assertEquals("line 20 " + "x".repeat(40), body[body.size - 2])
        assertEquals("", BugReport.tail(File(tmp.root, "none.log")))
    }

    @Test
    fun secretsAreBlankedInEveryShapeTheyTake() {
        val cases = mapOf(
            "api_key = \"sk-ant-api03-abcdefghijklmnop\"" to "api_key = [redacted]",
            "providers.models.custom.fake.api_key = not-needed" to "providers.models.custom.fake.api_key = [redacted]",
            "paired_tokens = [\"QmFzZTY0VG9rZW4\"]" to "paired_tokens = [redacted]",
            "x-caelza-admin-token: 0123456789abcdef" to "x-caelza-admin-token: [redacted]",
            "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.e30.abc" to "Authorization: [redacted]",
            "sent Bearer QmFzZTY0VG9rZW4= to the gateway" to "sent Bearer [redacted] to the gateway",
            "key sk-proj-ABCDEFGHIJKLMNOPQRSTUVWXYZ used" to "key [redacted] used",
            "GITHUB_TOKEN=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123" to "GITHUB_TOKEN=[redacted]",
            "telegram bot 123456789:AAHfiqksKZ8WmR2zSjiQ7_v4TMAKdiHm9T0 polling" to "telegram bot [redacted] polling",
            "GET /api/pair?token=abc123&x=1" to "GET /api/pair?token=[redacted]&x=1",
            "pairing_code: 482913" to "pairing_code: [redacted]",
            "password='hunter22'" to "password=[redacted]",
            // A JSON body: the quoted key keeps its quotes, the value goes.
            "{\"api_key\": \"sk-ant-api03-abcdefghijklmnop\", \"model\": \"x\"}" to "{\"api_key\": [redacted], \"model\": \"x\"}",
            "\"token\":\"QmFzZTY0VG9rZW4\"" to "\"token\":[redacted]",
            // The gateway's first-start banner boxes the pairing code (`caelza paircode` prints it the same way).
            "  │  482913  │" to "  │  [redacted]  │",
        )
        for ((input, expected) in cases) assertEquals(input, expected, BugReport.scrub(input))

        val untouched = listOf(
            "The token goes into this Body's state dir, never into the registry file.",
            "require_pairing = true",
            "caelza exited with exit code 1",
            "the admin token file is data/gateway-admin.token",
            "An API key is a password for a model provider.",
            "2026-11-01T08:35:00Z INFO gateway listening on 127.0.0.1:42617",
            "  ┌──────────────┐",
            "  │  caelza  │",
            "{\"model\": \"qwen\", \"temperature\": 0.2}",
        )
        for (line in untouched) assertEquals(line, BugReport.scrub(line))
    }

    @Test
    fun theReportNamesThePhoneAndEveryLogTheAppWritesWithoutARawSecret() {
        val home = tmp.root
        val store = RuntimeStore(home)
        store.logsDir.mkdirs()
        File(store.logsDir, "daemon.log").writeText("INFO gateway up\nWARN provider key sk-live-ABCDEFGHIJKLMNOP rejected\n")
        File(store.logsDir, "daemon.log.prev").writeText("older\n")
        File(store.logsDir, BugReport.INSTALL_LOG).writeText("found v0.1.0\nchecksum ok\n")
        store.versionDir("0.1.0").mkdirs()
        File(store.binary("0.1.0").path).writeText("#!/bin/sh\n")
        store.promote("0.1.0")
        File(store.versionDir("0.1.0"), "probe.log").writeText("probe: /health ok\n")

        val sources = BugReport.sources(store, home)
        assertEquals(listOf("daemon", "llama", "install", "probe", "body"), sources.map { it.id })
        assertEquals(File(store.logsDir, "daemon.log"), BugReport.byId(sources, null).file)
        assertEquals("install", BugReport.byId(sources, "install").id)
        assertEquals(File(home, ".caelza-body/logs/device-actions.log"), sources.last().file)

        val report = BugReport.render(listOf("app" to "0.1.0 (1)", "device" to "TCL REVVL, Android 13"), sources, Instant.parse("2026-11-01T08:35:00Z"))
        assertTrue(report.startsWith("# Caelza bug report\ngenerated: 2026-11-01T08:35:00Z\n"))
        assertTrue(report.contains("## This phone\napp: 0.1.0 (1)\ndevice: TCL REVVL, Android 13\n"))
        for (label in listOf("daemon.log", "daemon.log (previous)", "llama-server.log", BugReport.INSTALL_LOG, "probe.log", "device-actions.log")) {
            assertTrue(label, report.contains("\n## $label\n"))
        }
        assertTrue(report.contains("INFO gateway up\nWARN provider key [redacted] rejected\n"))
        assertFalse(report.contains("sk-live"))
        assertTrue("a log not written yet is said, not skipped", report.contains("llama-server.log: ${BugReport.MISSING}"))
        assertTrue(report.contains("probe: /health ok"))
        assertTrue(report.contains("older"))
    }

    @Test
    fun appendStampsLinesAndRotatesTheInstallLog() {
        val file = File(tmp.root, "logs/${BugReport.INSTALL_LOG}")
        BugReport.append(file, "found v0.1.0", Instant.parse("2026-11-01T08:35:00Z"))
        BugReport.append(file, "checksum ok", Instant.parse("2026-11-01T08:35:01Z"))
        assertEquals("2026-11-01T08:35:00Z found v0.1.0\n2026-11-01T08:35:01Z checksum ok\n", file.readText())

        file.writeText("x".repeat((BugReport.INSTALL_LOG_ROTATE_BYTES + 1).toInt()))
        BugReport.append(file, "after the turn")
        assertTrue(File(tmp.root, "logs/${BugReport.INSTALL_LOG}.prev").length() > BugReport.INSTALL_LOG_ROTATE_BYTES)
        assertTrue(file.readText().endsWith(" after the turn\n") && file.length() < 100)
    }

    @Test
    fun sizesReadLikeAPerson() {
        assertEquals("47 B", BugReport.human(47))
        assertEquals("1.5 KiB", BugReport.human(1536))
        assertEquals("312 KiB", BugReport.human(312L * 1024))
        assertEquals("1.2 GiB", BugReport.human((1.2 * 1024 * 1024 * 1024).toLong()))
        assertEquals("caelza-bug-report-20261101-083500.txt", BugReport.fileName(Instant.parse("2026-11-01T08:35:00Z")))
    }
}
