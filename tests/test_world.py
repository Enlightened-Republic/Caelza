"""Ether Hollow: the agent as a resident of the town, slice 1 (the Runtime side).

The `ether_hollow` tool mirrors the town's Agent API action for action with the
resident key the owner holds in `[ether_hollow]`; the gateway's `/api/world`
registers the resident (the key written through the config API's own PATCH
handler, never shown), and keeps the ghost visible (`here` every ~10 s while
the owner has sent the agent to town). These tests keep the overlay modules,
the patch, the manifest and the docs saying the same thing; the modules' own
behaviour is under `cargo test -p caelza-tools ether_hollow` and
`cargo test -p caelza-gateway api_world`.
"""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
TOOL = (OVERLAY / "crates" / "caelza-tools" / "src" / "ether_hollow.rs").read_text()
API = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_world.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0018-ether-hollow.patch").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
VISION = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()

TOWN = "https://etherhollow.enlightenedrepublic.online"
# The Agent API v1's actions, as `GET /api/agent` lists them (read 2026-11-16).
ACTIONS = [
    "register", "me", "town", "look", "move", "here", "leave", "read", "item", "buy",
    "events", "rsvp", "attend", "note", "list", "unlist", "listings", "orders", "order_done",
    "agreement", "rent", "rent_pay", "unrent", "lease", "post", "reply", "react",
    "build", "unbuild", "builds",
]


def rust_str_list(source: str, name: str) -> list[str]:
    body = re.search(rf"pub const {name}: &\[&str\] = &\[(.*?)\];", source, flags=re.S).group(1)
    return re.findall(r'"([a-z_]+)"', body)


def test_the_patch_touches_the_schema_the_tool_registry_and_the_gateway_only():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == [
        "crates/caelza-config/src/schema.rs",
        "crates/caelza-tools/src/lib.rs",
        "crates/caelza-tools/src/attribution.rs",
        "crates/caelza-tools/src/inventory.rs",
        "crates/caelza-runtime/src/tools/mod.rs",
        "crates/caelza-runtime/src/agent/loop_.rs",
        "crates/caelza-gateway/src/lib.rs",
        "docs/book/src/developing/tool-inventory.md",
    ], files
    # The book's tier-3 table, which the tools crate's docs-drift test reads.
    assert "+| Caelza | `ether_hollow` | No: `[ether_hollow].enabled` is off until the owner registers the resident |" in PATCH
    # The schema: the section, grouped, the key a secret, the proxy service key.
    assert "+    pub ether_hollow: EtherHollowConfig," in PATCH
    assert '+    #[group = "Integrations"]\n+    pub ether_hollow' in PATCH
    assert '+#[prefix = "ether_hollow"]' in PATCH
    assert "+    #[secret]\n+    #[credential_class = \"encrypted_secret\"]" in PATCH
    assert '+    "tool.ether_hollow",' in PATCH
    assert f'+            url: "{TOWN}".into(),' in PATCH
    assert "+            ether_hollow: EtherHollowConfig::default()," in PATCH
    # The tool: module, attribution, inventory, registration for the one agent.
    assert "+pub mod ether_hollow;" in PATCH
    assert "+tool_attribution!(EtherHollowTool, ToolKind::Plugin);" in PATCH
    assert '+        name: "ether_hollow",\n+        tier: ToolTier::Optional,\n+        compilation: BuiltinToolCompilation::Always,' in PATCH
    assert "+    if root_config.ether_hollow.enabled && agent_alias == root_config.ether_hollow.agent {" in PATCH
    assert "+            Arc::new(EtherHollowTool::new(&root_config.ether_hollow))" in PATCH
    assert "+        if config.ether_hollow.enabled {\n+            tool_descs.push((\n+                \"ether_hollow\"," in PATCH
    # The gateway: the module and its four routes.
    assert "+pub mod api_world;" in PATCH
    for route, handler in (
        ('"/api/world"', "get(api_world::handle_world_get)"),
        ('"/api/world/register"', "post(api_world::handle_world_register)"),
        ('"/api/world/enter"', "post(api_world::handle_world_enter)"),
        ('"/api/world/leave"', "post(api_world::handle_world_leave)"),
    ):
        assert f"+        .route({route}, {handler})" in PATCH, route


def test_the_tool_knows_every_action_the_town_has_and_which_ones_spend():
    assert rust_str_list(TOOL, "ACTIONS") == ACTIONS
    assert rust_str_list(TOOL, "SPEND_ACTIONS") == ["buy", "rent", "rent_pay"]
    assert f'pub const DEFAULT_URL: &str = "{TOWN}";' in TOOL
    assert 'pub const AGENT_PATH: &str = "/api/agent";' in TOOL
    assert 'pub const KEY_PREFIX: &str = "ehk_";' in TOOL and "pub const KEY_LEN: usize = 36;" in TOOL
    assert 'pub const SERVICE_KEY: &str = "tool.ether_hollow";' in TOOL
    assert 'pub const SERVICE_KEY: &str = "tool.ether_hollow";' in API, "one proxy rule covers the tool and the gateway"


def test_the_tool_refuses_before_the_network_what_is_not_the_models():
    # register is the owner's; no key means no resident; spending is off until allowed.
    assert 'Kind::Register => Some(' in TOOL and "Registration is the owner's" in TOOL
    assert "_ if !has_key => Some(" in TOOL and "not a resident of Ether Hollow yet" in TOOL
    assert "Kind::Spend if !spend_allowed => Some(format!(" in TOOL
    assert "if let Some(why) = refusal(&action, self.has_key(), self.spend) {" in TOOL
    # The key goes in the header, the model's own fields are dropped, the town's answer is the result.
    assert "request = request.bearer_auth(key);" in TOOL
    assert 'const LOCAL_FIELDS: &[&str] = &["approved"];' in TOOL
    assert "Ok((200, answer)) => Ok(ToolResult::ok(ToolOutput::json(answer)))," in TOOL
    assert "Ok((status, answer)) => Ok(ToolResult::err(explain(status, &answer)))," in TOOL
    for code in ("401", "402", "403", "423", "429", "503"):
        assert f"        {code} => " in TOOL, code
    # The key is never logged: the module logs nothing at all.
    assert "caelza_log::record!" not in TOOL


def test_the_gateway_keeps_the_key_and_the_presence():
    # Registration writes through the config API's own PATCH handler.
    assert "api_config::handle_patch(" in API
    assert "Json(register_ops(&key, &name))," in API
    for path in ("/ether_hollow/key", "/ether_hollow/name", "/ether_hollow/enabled"):
        assert f'"path": "{path}"' in API, path
    # The key is in the answer only when the write failed.
    assert "if !saved {" in API and 'out["key"] = Value::String(key);' in API
    assert API.count('out["key"]') == 1
    # The passport is scrubbed of anything key-shaped before it reaches the page.
    assert "Ok((200, v)) => (Some(scrub(v)), None)," in API
    # Presence: the town's ten seconds, an hour by default, a day at most, fatal codes end it.
    assert "pub const BEAT: Duration = Duration::from_secs(10);" in API
    assert "pub const DEFAULT_MINUTES: u64 = 60;" in API and "pub const MAX_MINUTES: u64 = 24 * 60;" in API
    assert "matches!(status, 401 | 403 | 423)" in API
    assert 'Some(&json!({"action": "here"}))' in API and API.count('{"action": "leave"}') == 2
    # The key is read live at every beat, so a removed key stops the ghost.
    assert "let Some(key) = live_key(&state) else {" in API
    # Every route is behind pairing.
    assert API.count("require_auth(&state, &headers)") == 5
    assert "caelza_log::record!" not in API


DOOR = (OVERLAY / "web" / "src" / "pages" / "connect" / "World.tsx").read_text()
DOOR_LOGIC = (OVERLAY / "web" / "src" / "pages" / "connect" / "world.logic.ts").read_text()
DOOR_LOGIC_TEST = (OVERLAY / "web" / "src" / "pages" / "connect" / "world.logic.test.ts").read_text()
CONNECT_PAGE = (OVERLAY / "web" / "src" / "pages" / "connect" / "Connect.tsx").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "world.ts").read_text()
DOOR_PATCH = (REPO_ROOT / "runtime" / "patches" / "0019-world-door.patch").read_text()
WAKE_PATCH = (REPO_ROOT / "runtime" / "patches" / "0020-world-wake.patch").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
CORPUS = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
APP_CORPUS = (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()


def test_the_door_is_on_the_connect_page_and_talks_only_to_the_gateway():
    assert 'import WorldCard from "./World";' in CONNECT_PAGE
    assert "<WorldCard agent={agent} disabled={!ready} />" in CONNECT_PAGE
    assert 'data-connect="world"' in DOOR
    # The four calls the gateway offers, nothing straight to the town.
    for fn, path in (("getWorld", "/api/world"), ("registerWorld", "/api/world/register"), ("enterWorld", "/api/world/enter"), ("leaveWorld", "/api/world/leave")):
        assert f"export function {fn}(" in CLIENT and f"'{path}'" in CLIENT, fn
    assert TOWN not in CLIENT and "api/agent" not in CLIENT and "api/agent" not in DOOR
    # Register sends the name, the line, the swatches and the tag; the key never reaches the page unless the write failed.
    assert "registerWorld({ name: name.trim(), bio: bio.trim() || undefined, look, color: chosenTag })" in DOOR
    assert "if (!r.saved) {" in DOOR and "setError(r.error ?? t(\"world.failed\"))" in DOOR
    assert "r.key" not in DOOR, "the page never reads the key"
    # The spending switch is the card's one config write; a visit is one of three lengths.
    assert "await patchConfig(spendOps(on));" in DOOR
    assert "export const VISITS = [15, 60, 240] as const;" in DOOR_LOGIC
    assert 'export const NAME_RULE = /^[A-Za-z0-9 _-]{3,24}$/;' in DOOR_LOGIC
    assert "export function lookFor(" in DOOR_LOGIC and "export function tagFor(" in DOOR_LOGIC
    for name in ("nameOk", "bioOk", "lookFor", "tagFor", "spendOps", "rcText", "minutesLeft"):
        assert f"{name}(" in DOOR_LOGIC_TEST, name


def test_the_door_patch_carries_its_strings_the_sentence_and_the_test():
    files = re.findall(r"^\+\+\+ b/(.+)$", DOOR_PATCH, flags=re.M)
    assert files == ["web/package.json", "web/src/lib/i18n.ts"], files
    assert "src/pages/connect/connect.logic.test.ts src/pages/connect/world.logic.test.ts " in DOOR_PATCH
    used = set(re.findall(r'"(world\.[a-z_0-9]+)"', DOOR))
    used |= {f"world.color_{c}" for c in ("cyan", "gold", "magenta", "lime", "orange", "violet")}
    used |= {f"world.visit_{m}" for m in (15, 60, 240)}
    added = set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", DOOR_PATCH, re.M))
    added |= set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", WAKE_PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    for key, phrase in (
        ("world.body", "100 RC = $1"),
        ("world.registered", "Reload daemon"),
        ("world.spend_note", "asks you first"),
        ("world.register_try", "Visiting is free"),
    ):
        line = re.search(rf"^\+    '{re.escape(key)}': (.*),$", DOOR_PATCH, re.M).group(1)
        assert phrase in json.loads(line), key
    screen = re.search(r"^\+    'guide\.screen_connect': (.*),$", DOOR_PATCH, re.M).group(1)
    assert "Ether Hollow card" in json.loads(screen)
    removed = [l for l in DOOR_PATCH.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert len(removed) == 2, removed


def test_the_faq_and_the_corpus_say_how_to_live_in_the_town():
    assert "## Can Cael live in Ether Hollow?" in FAQ
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    for phrase in ("Connect page", "never shows it", "Reload daemon bar", "Send to town", "100 RC = $1", "Spending RC"):
        assert phrase in section, phrase
    assert "Can Cael live in Ether Hollow?" in CORPUS
    assert CORPUS == APP_CORPUS, "the app's copy of the corpus is the rebuilt one"


def test_the_town_wakes_the_agent_through_a_cron_job_it_never_schedules():
    # The switch in the schema, the route, the waker started with the gateway.
    files = re.findall(r"^\+\+\+ b/(.+)$", WAKE_PATCH, flags=re.M)
    assert files == ["crates/caelza-config/src/schema.rs", "crates/caelza-gateway/src/lib.rs", "web/src/lib/i18n.ts"], files
    assert "+    pub wake: bool,\n" in WAKE_PATCH and "+            wake: false,\n" in WAKE_PATCH
    assert '+        .route("/api/world/wake", post(api_world::handle_world_wake))' in WAKE_PATCH
    assert "+    api_world::start_waker(state.clone());" in WAKE_PATCH
    # The waker: what it reads, what wakes, how often, with which tools.
    assert 'pub const JOB_NAME: &str = "ether-hollow";' in API
    assert "pub const POLL_IN_TOWN: Duration = Duration::from_secs(60);" in API
    assert "pub const POLL_AWAY: Duration = Duration::from_secs(120);" in API
    assert "pub const MIN_GAP: Duration = Duration::from_secs(10 * 60);" in API
    assert "pub const RENT_SOON_SECS: i64 = 48 * 3600;" in API
    assert 'pub const WAKE_TOOLS: &[&str] = &["ether_hollow", "memory_recall", "memory_store"];' in API
    for variant in ("Mention {", "Order {", "RentDue {", "Timeout {"):
        assert variant in API, variant
    assert "seen.primed = true;" in API, "the first read primes"
    # The job: made once, never on its own, isolated, memory on, re-prompted each wake, run as the manual trigger runs it.
    assert "Schedule::At { at: now + chrono::Duration::days(365 * 100) }" in API
    assert "SessionTarget::Isolated," in API and "Some(DeliveryConfig::default())," in API
    assert "cron::resolve_job_id_or_name(&config, JOB_NAME, &agent)" in API
    assert "run_manual_job_with_selection(&config, &job, CronDeliveryContext::GatewayManual, &event_tx, Some(selection))" in API
    assert "answer exactly NO_REPLY" in API and "do not pay it yourself" in API
    # The card: the switch, the line, Wake now; the client's call.
    assert "await patchConfig(wakeOps(on));" in DOOR and 'data-world-action="wake"' in DOOR and "data-world-wake-line" in DOOR
    assert "export function wakeOps(" in DOOR_LOGIC and "export function wakeLine(" in DOOR_LOGIC
    assert "export function wakeWorld(" in CLIENT and "'/api/world/wake'" in CLIENT
    used = set(re.findall(r'"(world\.wake[a-z_0-9]*)"', DOOR)) | set(re.findall(r'"(world\.woke|world\.waking)"', DOOR))
    added = set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", WAKE_PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    note = re.search(r"^\+    'world\.wake_note': (.*),$", WAKE_PATCH, re.M).group(1)
    assert "once every ten minutes" in json.loads(note) and "never spends" in json.loads(note)
    # The FAQ and the corpus say it.
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "Let the town wake your agent" in section and "once every ten minutes" in section
    assert "wake your agent" in CORPUS and CORPUS == APP_CORPUS
    assert MANIFEST["components"]["runtime"]["world_wake_patch"] == "runtime/patches/0020-world-wake.patch"
    assert "**Slice 3 (the town wakes the agent):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]


def test_the_manifest_and_the_vision_name_the_slice():
    rt = MANIFEST["components"]["runtime"]
    assert rt["world_door"] == "runtime/overlay/web/src/pages/connect/World.tsx"
    assert rt["world_door_patch"] == "runtime/patches/0019-world-door.patch"
    assert "**Slice 2 (the door):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]
    rt = MANIFEST["components"]["runtime"]
    assert rt["world_patch"] == "runtime/patches/0018-ether-hollow.patch"
    assert rt["world_tool"] == "runtime/overlay/crates/caelza-tools/src/ether_hollow.rs"
    assert rt["world_api"] == "runtime/overlay/crates/caelza-gateway/src/api_world.rs"
    assert rt["world_url"] == TOWN
    assert "| **M10 Ether Hollow** |" in VISION
    row = VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]
    assert "0018-ether-hollow.patch" in row and "`ether_hollow`" in row and "/api/world" in row
    assert "Left:" in row, "the slices still to come are named"
