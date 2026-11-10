"""The Connect page: your apps, your home, your printer from the dashboard, with no shell.

The `[[mcp.servers]]` row is a keyed list entry, which no `caelza config set`
path can create (`mcp.servers.maton.transport` is "Unknown property" until
the row exists; the Runtime answered that to the first connect scripts), so
the page makes the row by name through `POST /api/config/map-key` and fills
it, bundles it and grants it in one `PATCH /api/config`; the scripts do the
same with `caelza config patch`. The 3D printer is a skill, which the config
API cannot put on disk, so the gateway's api_connect.rs (an overlay module)
writes the copy runtime/build.sh embeds. These tests keep the page, the
module, the patch, the scripts and the docs saying the same thing.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
PAGE_DIR = OVERLAY / "web" / "src" / "pages" / "connect"
PAGE = (PAGE_DIR / "Connect.tsx").read_text()
LOGIC = (PAGE_DIR / "connect.logic.ts").read_text()
LOGIC_TEST = (PAGE_DIR / "connect.logic.test.ts").read_text()
GATEWAY = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_connect.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0015-connect.patch").read_text()
BUILD_SH = (REPO_ROOT / "runtime" / "build.sh").read_text()
GUIDE = (OVERLAY / "web" / "src" / "guide" / "guide.logic.ts").read_text()
CAEL_BUTTON = (OVERLAY / "web" / "src" / "guide" / "CaelButton.tsx").read_text()
BRAND_CSS = (OVERLAY / "web" / "src" / "caelza-brand.css").read_text()
SKILL = (REPO_ROOT / "skills" / "3d-printer" / "SKILL.md").read_text()
MATON_EXAMPLE = tomllib.loads((REPO_ROOT / "runtime" / "caelza.maton.example.toml").read_text())
HA_EXAMPLE = tomllib.loads((REPO_ROOT / "runtime" / "caelza.homeassistant.example.toml").read_text())
PRINTER_EXAMPLE = (REPO_ROOT / "runtime" / "caelza.printer.example.toml").read_text()
README = (REPO_ROOT / "README.md").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()


def test_the_page_makes_the_row_by_name_then_fills_it_in_one_patch():
    assert "await patchConfig(serverOps(spec.name, spec.url, spec.timeout, bearer(spec.secret), agent, known.bundles));" in PAGE
    assert "await patchConfig(printerOps(host, printerKind, octoKey, known.hosts));" in PAGE
    assert "await installConnectSkill(PRINTER_SKILL, agent);" in PAGE
    # The patch's ops, in JSON-pointer form, cover the row, its bundle and the agent's grant.
    for path in ("/mcp/servers/${name}/url", "/mcp/servers/${name}/transport", "/mcp/servers/${name}/tool_timeout_secs",
                 "/mcp/servers/${name}/headers/Authorization", "/mcp_bundles/${name}/servers", "/agents/${agent}/mcp_bundles"):
        assert f"path: `{path}`" in LOGIC, path
    assert 'path: "/http_request/allowed_private_hosts"' in LOGIC
    assert "path: `/http_request/secrets/${OCTOPRINT_SECRET}`" in LOGIC
    # A secret never shows again: connected means the list says the header is populated.
    assert "auth?.populated === true" in LOGIC
    assert 'type={shown ? "text" : "password"}' in PAGE
    # A row made and never filled (stdio, no command) fails the whole config's validation and
    # every later write with it: when the fill fails, a row this press made goes again.
    assert 'created = (await createMapKey("mcp.servers", spec.name)).created;' in PAGE
    assert 'await deleteMapKey("mcp.servers", spec.name);' in PAGE
    assert "  deleteMapKey,\n" in PAGE.split('} from "@/lib/api";')[0], "upstream's own DELETE /api/config/map-key client"
    # Before Set up there is no agent to grant to: the cards wait and point at Set up.
    assert "const noAgent = known !== null && known.agents.length === 0;" in PAGE
    assert 'if (busy || !known || noAgent) return;' in PAGE
    assert '<Link to="/setup" className="cz-link">' in PAGE
    # A write that landed stays Done even when the re-read fails; the key leaves its box first.
    assert "setKnown(await readKnown());\n    } catch {" in PAGE


def test_the_logic_agrees_with_the_example_configs_and_the_skill():
    (maton,) = MATON_EXAMPLE["mcp"]["servers"]
    assert f'url: "{maton["url"]}"' in LOGIC and f'timeout: {maton["tool_timeout_secs"]}' in LOGIC
    (ha,) = HA_EXAMPLE["mcp"]["servers"]
    assert ha["url"].endswith("/api/mcp/assist") and 'path: "/api/mcp/assist"' in LOGIC
    assert f'defaultAddress: "{ha["url"].removesuffix("/api/mcp/assist")}"' in LOGIC
    assert f'timeout: {ha["tool_timeout_secs"]}' in LOGIC
    assert 'name: "maton"' in LOGIC and 'name: "homeassistant"' in LOGIC
    assert 'export const OCTOPRINT_SECRET = "octoprint";' in LOGIC and 'auth_secret:\n"octoprint"' in SKILL.replace("`", "")
    assert "allowed_private_hosts" in PRINTER_EXAMPLE and 'export const PRINTER_SKILL = "3d-printer";' in LOGIC
    assert SKILL.startswith("---\nname: 3d-printer\n")


def test_the_gateway_puts_the_bundled_skill_in_the_agents_workspace():
    assert 'cp "$ROOT/skills/3d-printer/SKILL.md" "$WORK/crates/caelza-gateway/src/connect_skill_3d_printer.md"' in BUILD_SH
    assert '("3d-printer", include_str!("connect_skill_3d_printer.md"))' in GATEWAY
    assert 'config.agent_workspace_dir(agent).join("skills")' in GATEWAY, "workspace skills load with no bundle"
    assert "require_auth(&state, &headers)" in GATEWAY
    assert "std::fs::rename(&tmp, path)" in GATEWAY, "written whole or not at all"
    assert "+pub mod api_connect;" in PATCH
    assert '+        .route("/api/connect/skills", get(api_connect::handle_skills_get))' in PATCH
    assert '+        .route("/api/connect/skills/{name}", post(api_connect::handle_skill_install))' in PATCH
    assert "`/api/connect/skills?agent=${encodeURIComponent(agent)}`" in PATCH
    assert "`/api/connect/skills/${encodeURIComponent(name)}`" in PATCH


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == [
        "crates/caelza-gateway/src/lib.rs",
        "web/package.json",
        "web/src/components/layout/Header.tsx",
        "web/src/components/layout/Layout.tsx",
        "web/src/components/layout/Sidebar.tsx",
        "web/src/lib/api.ts",
        "web/src/lib/i18n.ts",
        "web/src/router/lazyPages.tsx",
        "web/src/router/router.tsx",
    ]
    # Insertions, plus the one replaced line (the test list): an existing line reordered would show up here too.
    removed = [l for l in PATCH.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert len(removed) == 1 and removed[0].startswith('-    "test": "node --experimental-strip-types --test'), removed


def test_the_page_is_routed_titled_explained_and_tested():
    assert '+        <Route path="/connect" element={<Connect />} />' in PATCH
    assert "+export const Connect = lazy(() => import('../pages/connect/Connect'));" in PATCH
    assert "+      { to: '/connect', icon: Cable, labelKey: 'nav.connect' }," in PATCH
    assert PATCH.count("+  connect: 'nav.connect',") == 2, "the top bar's two title maps"
    assert "+    'nav.connect': 'Connect'," in PATCH
    assert "src/pages/connect/connect.logic.test.ts" in PATCH
    # Cael explains the screen and knows its title.
    assert '  connect: "connect",' in GUIDE and '    connect: "/agents",' in GUIDE and '| "connect"' in GUIDE
    assert '  connect: "nav.connect",' in CAEL_BUTTON
    assert "+    'guide.screen_connect': " in PATCH and "+    'guide.next_connect': " in PATCH
    assert ".cz-connect {" in BRAND_CSS


def test_every_string_the_page_uses_is_in_the_patch():
    used = set(re.findall(r'"(connect\.[a-z_]+)"', PAGE))
    added = set(re.findall(r"^\+    '(connect\.[a-z_]+)': ", PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    for key, phrase in (
        ("connect.cael", "asks you first"),
        ("connect.apps_body", "treat it like a password"),
        ("connect.printer_body", "never starts prints"),
        ("connect.done", "next time it starts"),
    ):
        line = re.search(rf"^\+    '{re.escape(key)}': (.*),$", PATCH, re.M).group(1)
        assert phrase in json.loads(line), key


def test_the_docs_point_at_the_connect_page_and_the_readme_no_longer_calls_it_coming():
    assert "Planned, not shipped yet" not in README
    assert "**Connect**" in README and "Maton" in README and "Home Assistant" in README and "OctoPrint" in README
    for heading in ("## How do I connect my apps", "## How do I connect my smart home", "## Can Caelza watch my 3D printer?"):
        section = " ".join(FAQ.split(heading, 1)[1].split("\n## ", 1)[0].split())
        assert "Connect page" in section, heading
    assert "connect.logic.test.ts" in LOGIC_TEST or "serverOps" in LOGIC_TEST
