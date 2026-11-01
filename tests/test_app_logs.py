"""The logs in the app (android-app.md §2 "Logs"; the §6 item closed).

`logs/LogsActivity.kt` shows the end of each log the app writes, secrets
blanked, and shares a bug report through a FileProvider; `logs/BugReport.kt`
is the testable part (BugReportTest). These tests pin the wiring: the manifest,
the provider's one directory, the file names against the code that writes
them, the strip's button, the docs.
"""
from __future__ import annotations

import re
from pathlib import Path
from xml.dom import minidom

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android" / "app"
KT = APP / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
RES = APP / "src" / "main" / "res"
MANIFEST = (APP / "src" / "main" / "AndroidManifest.xml").read_text()
MAIN = (KT / "MainActivity.kt").read_text()
FIRST_RUN = (KT / "firstrun" / "FirstRunActivity.kt").read_text()
SERVICE = (KT / "RuntimeService.kt").read_text()
INSTALLER = (KT / "runtime" / "ReleaseInstaller.kt").read_text()
LOGS = (KT / "logs" / "LogsActivity.kt").read_text()
REPORT = (KT / "logs" / "BugReport.kt").read_text()
LAYOUT_MAIN = (RES / "layout" / "activity_main.xml").read_text()
LAYOUT_LOGS = (RES / "layout" / "activity_logs.xml").read_text()
STRINGS = (RES / "values" / "strings.xml").read_text()
FILE_PATHS = (RES / "xml" / "file_paths.xml").read_text()
DESIGN = (REPO_ROOT / "docs" / "design" / "android-app.md").read_text()
README = (REPO_ROOT / "android" / "README.md").read_text()
BUNDLE = (REPO_ROOT / "bundle" / "manifest.toml").read_text()


def test_the_logs_screen_is_declared_and_the_provider_serves_only_the_report_dir():
    assert re.search(r'<activity\s+android:name="\.logs\.LogsActivity"\s+android:exported="false"', MANIFEST)
    provider = re.search(r'<provider\s+android:name="androidx\.core\.content\.FileProvider"(.*?)</provider>', MANIFEST, re.S).group(1)
    assert 'android:authorities="${applicationId}.files"' in provider
    assert 'android:exported="false"' in provider and 'android:grantUriPermissions="true"' in provider
    assert 'android:resource="@xml/file_paths"' in provider
    paths = minidom.parseString(FILE_PATHS).documentElement
    assert paths.tagName == "paths"
    entries = [e for e in paths.childNodes if e.nodeType == e.ELEMENT_NODE]
    assert [(e.tagName, e.getAttribute("path")) for e in entries] == [("cache-path", "bugreport/")], "the report dir and nothing else"
    assert 'const val REPORT_DIR = "bugreport"' in REPORT
    assert 'File(cacheDir, BugReport.REPORT_DIR)' in LOGS
    assert '"${BuildConfig.APPLICATION_ID}.files"' in LOGS, "the authority the manifest declares"
    assert "Intent.FLAG_GRANT_READ_URI_PERMISSION" in LOGS and 'setType("text/plain")' in LOGS


def test_the_viewer_shows_the_logs_the_app_writes_under_their_own_names():
    for name in ("daemon.log", "llama-server.log"):
        assert f'File(store.logsDir, "{name}")' in SERVICE, f"RuntimeService writes {name}"
        assert f'"{name}"' in REPORT and f'"{name}.prev"' in REPORT, f"the viewer reads {name} and the rotation's .prev"
    assert 'File(binary.parentFile, "probe.log")' in INSTALLER and '"probe.log"' in REPORT
    assert "BodyHome.AUDIT_LOG" in REPORT, "the Body's audit log under its own constant"
    assert 'const val INSTALL_LOG = "install.log"' in REPORT
    assert "BugReport.append(installLog, line)" in MAIN, "the shell's installer lines reach install.log"
    assert "BugReport.append(installLog, it)" in FIRST_RUN, "the first run's installer lines reach install.log"
    assert 'BugReport.append(installLog, "failed:' in MAIN and 'BugReport.append(installLog, "failed:' in FIRST_RUN
    assert "BugReport.scrub(BugReport.tail(file))" in LOGS, "the viewer blanks secrets too, not only the report"
    assert "BugReport.render(header(), sources)" in LOGS
    for key in ("app", "device", "runtime", "runtime state", "body", "model", "shizuku", "storage", "memory"):
        assert f'"{key}" to ' in LOGS, f"the report's header says {key}"


def test_the_strip_and_the_halted_shell_open_the_logs():
    assert 'android:id="@+id/logsButton"' in LAYOUT_MAIN and 'android:text="@string/action_logs"' in LAYOUT_MAIN
    assert 'android:id="@+id/logsAction"' in LAYOUT_MAIN
    assert "binding.logsButton.setOnClickListener { startActivity(LogsActivity.intent(this)) }" in MAIN
    assert re.search(r"binding\.logsAction\.visibility = if \(state\.phase == RuntimeService\.Phase\.HALTED\) View\.VISIBLE else View\.GONE", MAIN)
    for view in ("backButton", "refreshButton", "shareButton", "sourceChips", "about", "logScroll", "logText", "footer"):
        assert f'android:id="@+id/{view}"' in LAYOUT_LOGS, view
    assert 'android:fontFamily="monospace"' in LAYOUT_LOGS and 'android:textIsSelectable="true"' in LAYOUT_LOGS
    assert 'app:singleSelection="true"' in LAYOUT_LOGS and 'app:selectionRequired="true"' in LAYOUT_LOGS
    assert (RES / "layout" / "chip_source.xml").is_file() and "R.layout.chip_source" in LOGS
    for key in ("logs_title", "logs_back", "logs_refresh", "logs_share", "logs_share_short", "logs_empty", "logs_footer",
                "logs_report_subject", "logs_report_text"):
        assert f'<string name="{key}">' in STRINGS, key


def test_the_docs_and_the_manifest_say_so():
    assert "**Logs.**" in DESIGN and "`BugReport.scrub`" in DESIGN
    assert "LogsActivity" in DESIGN.split("## 2.")[0], "the §1 diagram names the screen"
    open_items = DESIGN.split("## 6. Open items")[1]
    assert "Logs in the app" not in open_items, "the §6 item is closed"
    assert "logs/LogsActivity.kt" in README and "logs/BugReport.kt" in README
    keys = dict(re.findall(r'^(logs_screen|bug_report) = "([^"]+)"', BUNDLE, re.M))
    assert set(keys) == {"logs_screen", "bug_report"}
    for path in keys.values():
        assert (REPO_ROOT / path).is_file(), path
