#!/usr/bin/env python3
"""Write the Body contract the Android app's tests pin against.

The app's Body (`android/app/src/main/java/tech/enlightenedrepublic/caelza/body/`)
is `caelza_body`'s `device` group in Kotlin. Two fixtures keep the two in step,
checked from both sides (`tests/test_android_body.py` here, `BodyToolsTest`
and `PlaybooksTest` in Gradle):

    android/app/src/test/fixtures/body-tools.json      every `sensors` and `device` tool as `caelza-body list-tools` prints it
    android/app/src/test/fixtures/debloat-tables.json  the playbook tables (`python -m caelza_body.agent.playbooks`)

Run it after changing a sensor's or a device tool's schema or description, or
a playbook table; the Python tests say so when the fixtures are stale.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = REPO_ROOT / "android" / "app" / "src" / "test" / "fixtures"
TOOLS_FIXTURE = FIXTURES / "body-tools.json"
TABLES_FIXTURE = FIXTURES / "debloat-tables.json"

sys.path.insert(0, str(REPO_ROOT))

from caelza_body import mcp_server as srv  # noqa: E402
from caelza_body.agent import playbooks  # noqa: E402
from caelza_body.agent import tools  # noqa: E402


#: The groups the app's Body serves (less the four fleet tools, which need adb and the registry).
GROUPS = ("sensors", "device")


def device_tools() -> list[dict]:
    """The served groups' tools, sorted by name, as the MCP server lists them."""
    with tempfile.TemporaryDirectory() as home:
        srv.register_tools(srv.load_settings(Path(home), REPO_ROOT), GROUPS)
        try:
            listed = [t.model_dump(mode="json", exclude_none=True) for t in srv.mcp_tools()]
        finally:
            tools.reset()
    return sorted(listed, key=lambda t: t["name"])


def dump(data) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    TOOLS_FIXTURE.write_text(dump(device_tools()), encoding="utf-8")
    TABLES_FIXTURE.write_text(dump(playbooks.export_tables()), encoding="utf-8")
    print(f"wrote {TOOLS_FIXTURE.relative_to(REPO_ROOT)} and {TABLES_FIXTURE.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
