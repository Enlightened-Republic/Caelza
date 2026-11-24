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
# The Agent API v1.1's actions, as `GET /api/agent` lists them (read 2026-11-20; `news` 2026-11-24).
ACTIONS = [
    "register", "me", "town", "look", "move", "here", "leave", "read", "item", "buy", "buy_rc",
    "events", "rsvp", "attend", "note", "list", "unlist", "listings", "orders", "order_done",
    "agreement", "rent", "rent_pay", "unrent", "lease", "post", "reply", "react",
    "build", "unbuild", "builds", "news",
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
    assert rust_str_list(TOOL, "SPEND_ACTIONS") == ["buy", "buy_rc", "rent", "rent_pay"]
    # The field names the model is told are the spec's (unlist {id}, react {id, r}, order_done {order}).
    for field in ('"id":', '"r":', '"order":', '"mine":', '"ids":', '"all":', '"note":'):
        assert field in TOOL, field
    assert '"listing":' not in TOOL and '"post": {' not in TOOL
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
    assert "Json(register_ops(&town.path, &key, &name))," in API
    # The key and the name under the resident's own table; the switch is the town's.
    assert '"path": format!("{path}/key")' in API and '"path": format!("{path}/name")' in API
    assert '"path": "/ether_hollow/enabled"' in API
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
    assert "let Some(key) = live_key(&state, &alias) else {" in API
    # Ten routes, every one behind pairing: get, register, enter, leave, wake, lots, rent, rent/pay, redeem, home.
    assert API.count("require_auth(&state, &headers)") == 10
    assert "caelza_log::record!" not in API


DOOR = (OVERLAY / "web" / "src" / "pages" / "connect" / "World.tsx").read_text()
DOOR_LOGIC = (OVERLAY / "web" / "src" / "pages" / "connect" / "world.logic.ts").read_text()
DOOR_LOGIC_TEST = (OVERLAY / "web" / "src" / "pages" / "connect" / "world.logic.test.ts").read_text()
CONNECT_PAGE = (OVERLAY / "web" / "src" / "pages" / "connect" / "Connect.tsx").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "world.ts").read_text()
DOOR_PATCH = (REPO_ROOT / "runtime" / "patches" / "0019-world-door.patch").read_text()
WAKE_PATCH = (REPO_ROOT / "runtime" / "patches" / "0020-world-wake.patch").read_text()
RENT_PATCH = (REPO_ROOT / "runtime" / "patches" / "0021-world-rent.patch").read_text()
RESIDENTS_PATCH = (REPO_ROOT / "runtime" / "patches" / "0028-world-residents.patch").read_text()
DAY_PLAN_PATCH = (REPO_ROOT / "runtime" / "patches" / "0029-day-plan.patch").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
CORPUS = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()
APP_CORPUS = (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_text()


def test_the_door_is_on_the_connect_page_and_talks_only_to_the_gateway():
    assert 'import WorldCard from "./World";' in CONNECT_PAGE
    assert "<WorldCard agent={agent} agents={known?.agents ?? [agent]} disabled={!ready} />" in CONNECT_PAGE
    assert 'data-connect="world"' in DOOR
    # The four calls the gateway offers, nothing straight to the town.
    for fn, path in (("getWorld", "/api/world"), ("registerWorld", "/api/world/register"), ("enterWorld", "/api/world/enter"), ("leaveWorld", "/api/world/leave")):
        assert f"export function {fn}(" in CLIENT and f"'{path}'" in CLIENT, fn
    assert TOWN not in CLIENT and "api/agent" not in CLIENT and "api/agent" not in DOOR
    # Register sends the name, the line, the swatches and the tag; the key never reaches the page unless the write failed.
    assert "registerWorld({ name: name.trim(), bio: bio.trim() || undefined, look, color: chosenTag }, picked)" in DOOR
    assert "if (!r.saved) {" in DOOR and "setError(r.error ?? t(\"world.failed\"))" in DOOR
    assert "r.key" not in DOOR, "the page never reads the key"
    # The spending switch is the card's one config write; a visit is one of three lengths.
    assert "await patchConfig(spendOps(on, state.spend_path));" in DOOR
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
    added |= set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", RENT_PATCH, re.M))
    added |= set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", RESIDENTS_PATCH, re.M))
    added |= set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", DAY_PLAN_PATCH, re.M))
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
    assert "await patchConfig(wakeOps(on, profile, autoApprove));" in DOOR and 'data-world-action="wake"' in DOOR and "data-world-wake-line" in DOOR
    assert "getProp(`agents.${state.agent}.risk_profile`)" in DOOR and "getProp(`risk_profiles.${profile}.auto_approve`)" in DOOR
    assert 'export const WAKE_TOOLS = ["ether_hollow", "memory_recall", "memory_store"] as const;' in DOOR_LOGIC
    assert "path: `/risk_profiles/${profile}/auto_approve`" in DOOR_LOGIC
    assert "export function wakeOps(" in DOOR_LOGIC and "export function wakeLine(" in DOOR_LOGIC
    assert "export function wakeWorld(" in CLIENT and "'/api/world/wake'" in CLIENT
    used = set(re.findall(r'"(world\.wake[a-z_0-9]*)"', DOOR)) | set(re.findall(r'"(world\.woke|world\.waking)"', DOOR))
    added = set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", WAKE_PATCH, re.M))
    assert used and used <= added, sorted(used - added)
    note = re.search(r"^\+    'world\.wake_note': (.*),$", WAKE_PATCH, re.M).group(1)
    assert "once every ten minutes" in json.loads(note) and "never spends" in json.loads(note) and "auto-approve" in json.loads(note)
    # The FAQ and the corpus say it.
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "Let the town wake your agent" in section and "once every ten minutes" in section and "auto-approve" in section
    assert "wake your agent" in CORPUS and CORPUS == APP_CORPUS
    assert MANIFEST["components"]["runtime"]["world_wake_patch"] == "runtime/patches/0020-world-wake.patch"
    assert "**Slice 3 (the town wakes the agent):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]


HOME_PATCH = (REPO_ROOT / "runtime" / "patches" / "0027-world-home.patch").read_text()
HOME_PAGE = (OVERLAY / "web" / "src" / "pages" / "Home.tsx").read_text()
HOME_LOGIC = (OVERLAY / "web" / "src" / "pages" / "home.logic.ts").read_text()
HOME_LOGIC_TEST = (OVERLAY / "web" / "src" / "pages" / "home.logic.test.ts").read_text()
NOTE = (REPO_ROOT / "docs" / "design" / "ether-hollow-open-world.md").read_text()
APP = REPO_ROOT / "android" / "app" / "src"
APP_KT = APP / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
TOWN_WAKE_KT = (APP_KT / "world" / "TownWake.kt").read_text()
WATCHER_KT = (APP_KT / "world" / "TownWatcher.kt").read_text()
SERVICE_KT = (APP_KT / "RuntimeService.kt").read_text()
CAELZA_APP_KT = (APP_KT / "CaelzaApp.kt").read_text()
STRINGS = (APP / "main" / "res" / "values" / "strings.xml").read_text()
TOWN_WAKE_TEST = (APP / "test" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "world" / "TownWakeTest.kt").read_text()


def test_the_town_lives_in_the_mind_on_home_and_on_the_phone():
    """Slice 5, the Caelza half: episodes for the resident agent, the last wake in a file, Home's tile, the phone's word."""
    files = re.findall(r"^\+\+\+ b/(.+)$", HOME_PATCH, flags=re.M)
    assert files == ["crates/caelza-gateway/src/lib.rs"], files
    assert '+        .route("/api/world/home", get(api_world::handle_world_home))' in HOME_PATCH
    assert MANIFEST["components"]["runtime"]["world_home_patch"] == "runtime/patches/0027-world-home.patch"
    # The Mind: daily entries under town:, for wakes, visits and the owner's taps, through the agent's own memory handle.
    assert 'pub const MEMORY_PREFIX: &str = "town:";' in API and "MemoryCategory::Daily" in API
    for key in ('format!("wake:{at}")', 'format!("visit:{since}")', 'format!("registered:{at}")', 'format!("rent:{at}")', 'format!("paid:{at}")', 'format!("redeem:{at}")'):
        assert key in API, key
    assert "caelza_memory::create_memory_for_agent(&config, &alias, api_key.as_deref())" in API
    for fn in ("pub fn wake_episode(", "pub fn visit_episode(", "pub fn owner_episode(", "pub fn remember(", "fn remember_visit("):
        assert fn in API, fn
    assert "I looked and nothing needed doing." in API
    # The last wake in its file, back into the state when the gateway starts; the glance's five minutes.
    assert 'pub const WORLD_DIR: &str = "world";' in API and 'pub const LAST_WAKE_FILE: &str = "last-wake.json";' in API
    assert "if let Some(last) = load_last_wake(&root) {" in API and "let _ = save_last_wake(" in API
    assert "pub const GLANCE_MAX_AGE: Duration = Duration::from_secs(300);" in API and "pub async fn handle_world_home(" in API
    # Home: the client, the tile, the fourth column.
    assert "export function getWorldHome(): Promise<WorldHome> {" in CLIENT and "'/api/world/home'" in CLIENT
    assert "export function townTile(" in HOME_LOGIC and "export const TOWN_REASON_CHARS = 60;" in HOME_LOGIC
    assert "townTile(town.data, town.error)" in HOME_PAGE and "getWorldHome()," in HOME_PAGE
    assert 'className="grid gap-3 md:grid-cols-2 lg:grid-cols-4" data-testid="home-tiles"' in HOME_PAGE
    assert "townTile(" in HOME_LOGIC_TEST and "TOWN_REASON_CHARS" in HOME_LOGIC_TEST
    # The phone: the file watched, its own channel, the strings, the test.
    assert 'const val DIR = "world"' in TOWN_WAKE_KT and 'const val FILE = "last-wake.json"' in TOWN_WAKE_KT
    assert "FileObserver(dir.path, CLOSE_WRITE or MOVED_TO)" in WATCHER_KT and "prefs.getLong(KEY_SHOWN_AT, 0L)" in WATCHER_KT
    assert "startTownWatcher()" in SERVICE_KT and "stopTownWatcher()" in SERVICE_KT
    assert 'const val TOWN_CHANNEL_ID = "town"' in SERVICE_KT and "NotificationCompat.Builder(this, TOWN_CHANNEL_ID)" in SERVICE_KT
    assert "RuntimeService.TOWN_CHANNEL_ID" in CAELZA_APP_KT and "NotificationManager.IMPORTANCE_DEFAULT" in CAELZA_APP_KT
    for key in ("town_channel_name", "town_channel_description", "town_woke_title", "town_your_agent"):
        assert f'<string name="{key}">' in STRINGS, key
    assert "class TownWakeTest" in TOWN_WAKE_TEST
    # The docs, the FAQ and the corpus.
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "remembers its town life" in section and "Town tile" in section and "tells you when the town wakes your agent" in section
    assert "remembers its town life" in CORPUS and CORPUS == APP_CORPUS
    p5 = " ".join(NOTE.split("**P5 · The town in the Mind, and on Home (Caelza).**", 1)[1].split("**P6 ·", 1)[0].split())
    assert "Shipped 2026-11-23 (the Caelza half)" in p5
    assert "**Slice 5 (the town in the Mind, and on Home; the Caelza half, 2026-11-23):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]


def test_several_agents_can_live_in_town():
    """P6, the Caelza half: a resident per agent, the first where it was, the rest in their own tables; every route per alias."""
    files = re.findall(r"^\+\+\+ b/(.+)$", RESIDENTS_PATCH, flags=re.M)
    assert files == ["crates/caelza-config/src/schema.rs", "crates/caelza-runtime/src/tools/mod.rs", "web/src/lib/i18n.ts"], files
    assert MANIFEST["components"]["runtime"]["world_residents_patch"] == "runtime/patches/0028-world-residents.patch"
    # The schema: the map beside the first resident, the entry's secret key, the resolver.
    assert "+    pub residents: HashMap<String, EtherHollowResidentConfig>," in RESIDENTS_PATCH
    assert '+#[prefix = "ether_hollow.residents"]' in RESIDENTS_PATCH and "+pub struct EtherHollowResidentConfig {" in RESIDENTS_PATCH
    assert RESIDENTS_PATCH.count("+    #[secret]\n+    #[credential_class = \"encrypted_secret\"]") == 1
    assert "+    pub fn resident(&self, alias: &str) -> Option<EtherHollowResident> {" in RESIDENTS_PATCH
    assert "+    pub fn residents(&self) -> Vec<EtherHollowResident> {" in RESIDENTS_PATCH
    assert '+            path: format!("/ether_hollow/residents/{alias}"),' in RESIDENTS_PATCH
    # The tool for every resident agent, with its own key and switch.
    assert "+        if let Some(resident) = root_config.ether_hollow.resident(agent_alias) {" in RESIDENTS_PATCH
    assert "EtherHollowTool::from_parts(&root_config.ether_hollow.url, resident.key.clone(), resident.spend)" in RESIDENTS_PATCH
    assert "-    if root_config.ether_hollow.enabled && agent_alias == root_config.ether_hollow.agent {" in RESIDENTS_PATCH
    # The gateway: ?agent= on every route, state per alias, a second resident's table made first.
    assert "pub struct AgentQuery {" in API and "fn alias_of(state: &AppState, q: &AgentQuery) -> Result<String, Response>" in API
    assert API.count("Query(q): Query<AgentQuery>") == 10, "every route takes ?agent="
    assert "fn resident_in(cfg: &EtherHollowConfig, alias: &str) -> Resident" in API and "pub fn default_alias(cfg: &EtherHollowConfig) -> String" in API
    assert "api_config::handle_map_key(" in API and 'path: "ether_hollow.residents".to_string(), key: alias.clone()' in API
    for per_alias in ("fn with_presence<T>(alias: &str", "fn with_wake<T>(alias: &str", "fn remember_me(alias: &str, me: Value)", "async fn read_resident(state: &AppState, town: &Resident) -> Option<(String, WakeNews)>", "pub async fn wake_now(state: &AppState, alias: &str, reason: String)", "pub fn remember(state: &AppState, alias: &str, key: String, text: String)"):
        assert per_alias in API, per_alias
    assert '"spend_path": town.path,' in API and '"residents": residents_summary(&state),' in API
    assert "for town in residents {" in API, "one poll per resident"
    # The client, the card's resident row, the Connect page, Home's tile.
    assert "function q(agent?: string): string {" in CLIENT and "'/api/world' + q(agent)" in CLIENT and "'/api/world/register' + q(agent)" in CLIENT
    assert "spend_path: string;" in CLIENT and "residents: WorldResident[];" in CLIENT and "export interface WorldHome extends WorldHomeResident {" in CLIENT
    assert 'export function spendOps(on: boolean, path = "/ether_hollow"): PatchOp[] {' in DOOR_LOGIC
    assert "export function residentCandidates(" in DOOR_LOGIC and "export function residentStatus(" in DOOR_LOGIC
    assert "residentCandidates(" in DOOR_LOGIC_TEST and "residentStatus(" in DOOR_LOGIC_TEST
    assert "data-world-residents" in DOOR and "data-world-agent={picked}" in DOOR and "residentStatus(state?.residents, a)" in DOOR
    assert "<WorldCard agent={agent} agents={known?.agents ?? [agent]} disabled={!ready} />" in CONNECT_PAGE
    assert "residents?: TownResidentSlice[];" in HOME_LOGIC and "${inTown.length} of ${registered.length} in town" in HOME_LOGIC
    assert "1 of 2 in town" in HOME_LOGIC_TEST
    # The docs, the FAQ and the corpus.
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "Several of your agents can live in town" in section
    assert "Several of your agents can live in town" in CORPUS and CORPUS == APP_CORPUS
    p6 = " ".join(NOTE.split("**P6 · Several residents (Caelza + town).**", 1)[1].split("### Decided", 1)[0].split())
    assert "Shipped 2026-11-23 (the Caelza half)" in p6
    assert "**Several residents (P6, the Caelza half, 2026-11-23):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]


SHOP = (OVERLAY / "web" / "src" / "pages" / "Shop.tsx").read_text()
UNLOCK_SCRIPT = (REPO_ROOT / "scripts" / "unlock_codes.py").read_text()


def test_renting_is_the_owners_tap_behind_the_spending_switch():
    files = re.findall(r"^\+\+\+ b/(.+)$", RENT_PATCH, flags=re.M)
    assert files == ["crates/caelza-gateway/src/lib.rs", "web/src/lib/i18n.ts"], files
    for route, handler in (
        ('"/api/world/lots"', "get(api_world::handle_world_lots)"),
        ('"/api/world/rent"', "post(api_world::handle_world_rent)"),
        ('"/api/world/rent/pay"', "post(api_world::handle_world_rent_pay)"),
        ('"/api/world/redeem"', "post(api_world::handle_world_redeem)"),
    ):
        assert f"+        .route({route}, {handler})" in RENT_PATCH, route
    # The gate: rent and pay refuse while spending is off; nothing is sent to the town.
    assert "fn spend_gate(town: &Resident) -> Result<(), Response>" in API
    assert '"spending is off: turn Spending RC on in the Ether Hollow card first; nothing costs RC without it"' in API
    assert API.count("if let Err(r) = spend_gate(&town) {") == 2, "rent and pay"
    # Redeem: the Shop's check first, the amount from the pack, the town's redeem with the resident's key.
    assert "use super::api_looks::{UNLOCK_PUBLIC_KEY, verify_code};" in API
    assert "verify_code(code, UNLOCK_PUBLIC_KEY)" in API and "pub fn rc_amount(pack: &str) -> Option<u64>" in API
    assert 'json!({"action": "redeem", "code": compact})' in API
    # The waker under the new rules.
    assert "Missed { missed: u64, repossess_on: String }," in API and "Reset { on: String }," in API
    assert 'lease.get("missed").and_then(Value::as_u64)' in API and 'str_of(a, &["reset_on"])' in API
    # The card and the Shop.
    for attr in ('data-world-action="lots"', 'data-world-lot={l.id}', "data-world-agreement", "data-world-agree", 'data-world-action="rent"', 'data-world-action="pay"', "data-world-lease", "data-world-reset"):
        assert attr in DOOR, attr
    assert "disabled={!ready || !lot || !agreed || !state.spend || !lots.agreement.version}" in DOOR
    assert 'data-shop="rc"' in SHOP and "redeemWorld(rcCode.replace(" in SHOP and "rcCodeAmount(rcCode)" in SHOP
    for fn, path in (("getWorldLots", "/api/world/lots"), ("rentWorld", "/api/world/rent"), ("payWorldRent", "/api/world/rent/pay"), ("redeemWorld", "/api/world/redeem")):
        assert f"export function {fn}(" in CLIENT and f"'{path}'" in CLIENT, fn
    assert "export const RC_CODE_RULE = " in DOOR_LOGIC and "export function leaseLine(" in DOOR_LOGIC and "export function lotLabel(" in DOOR_LOGIC
    # The strings: every world.* key the card and the Shop use is in one of the four patches.
    used = set(re.findall(r'"(world\.[a-z_0-9]+)"', DOOR + SHOP))
    added = set()
    for patch in (DOOR_PATCH, WAKE_PATCH, RENT_PATCH, RESIDENTS_PATCH, DAY_PLAN_PATCH):
        added |= set(re.findall(r"^\+    '(world\.[a-z_0-9]+)': ", patch, re.M))
    assert used <= added, sorted(used - added)
    note = re.search(r"^\+    'world\.lease_note': (.*),$", RENT_PATCH, re.M).group(1)
    assert "on the 1st" in json.loads(note) and "Ninety days" in json.loads(note)
    # The script says what an RC code is; the FAQ says how it is used.
    assert "`mint --pack rc500`" in UNLOCK_SCRIPT
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    for phrase in ("Rent a lot", "nothing costs RC without it", "taken from the passport on the 1st", "RC for Ether Hollow", "a code works once"):
        assert phrase in section, phrase
    assert MANIFEST["components"]["runtime"]["world_rent_patch"] == "runtime/patches/0021-world-rent.patch"
    assert "**Slice 4 (renting and RC codes, the Caelza side):**" in VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]


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


def test_the_towns_news_reaches_the_mind_by_a_pull():
    """M10 slice 5a: the waker reads `news {since}`, remembers each item, feeds the inner life, wakes for what needs the agent."""
    # The tool has the action, as a read.
    assert "news" in rust_str_list(TOOL, "ACTIONS") and "news" not in rust_str_list(TOOL, "SPEND_ACTIONS")
    assert '"since": { "type": "integer"' in TOOL and "`news {since?}`" in TOOL
    # The waker: the read, the cursor on disk, the first read priming it.
    assert 'json!({"action": "news", "limit": NEWS_LIMIT})' in API and 'body["since"] = json!(cursor);' in API
    assert 'pub const NEWS_SINCE_FILE: &str = "news-since.json";' in API
    assert "for (alias, since) in load_news_since(&root) {" in API and "save_news_since(&root, &town.agent," in API
    assert "pub fn take_news(seen: &mut Seen, items: &[NewsItem], next: u64) -> Vec<NewsItem>" in API
    assert "seen.news_since = Some(next);\n        return Vec::new();" in API, "the first read primes"
    # Each item: an episode in the agent's own words, and the inner life where the Mind has it.
    assert 'remember(state, &town.agent, format!("news:{}", item.id), news_episode(item, now));' in API
    assert "pub fn first_person(text: &str) -> String" in API
    assert 'mind.call_tool_json(&alias, "brain_inner", inner_event_args(&inner, &item))' in API
    assert '"sale" | "town_sale" => "reward",' in API and '"event_soon" | "event" => "novelty",' in API
    assert '"timeout" | "suspend" | "ban" | "rent_missed" => "fine",' in API
    assert '"post_hidden" | "revoke" | "builds_cleared" => "rejection",' in API
    assert 'json!({"action": "bond", "who": who, "what": what, "valence": valence})' in API
    # What wakes: a mention or a reply (once per post), an RSVP'd event, a lost lease; the gap holds, it does not drop.
    for variant in ("Reply { id: String, who: String, text: String },", "EventSoon { id: String, title: String, start: String, place: String, started: bool },", "LeaseLost { lot: String },"):
        assert variant in API, variant
    assert "pub fn news_triggers(seen: &mut Seen, items: &[NewsItem], already: &[Trigger]) -> Vec<Trigger>" in API
    assert "seen.mentioned.insert(id.clone());" in API
    assert "pub fn due_now(w: &mut Wake, found: Vec<Trigger>, now: u64) -> Vec<Trigger>" in API
    assert "An event you RSVP'd to is starting: go, with {calls}." in API and "The town's news since your last wake:" in API
    # The docs, the FAQ and the corpus.
    six = NOTE.split("6. **Feeding the Mind**", 1)[1].split("\n7. ", 1)[0]
    assert "(pull; shipped town side 2026-11-24" in six and "behind NAT" in six
    p5 = " ".join(NOTE.split("**P5 · The town in the Mind, and on Home (Caelza).**", 1)[1].split("**P6 ·", 1)[0].split())
    assert "**The town's news (slice 5a, 2026-11-24):**" in p5
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "reads the town's news for your agent" in section
    assert "reads the town's news for your agent" in CORPUS and CORPUS == APP_CORPUS
    row = VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]
    assert "**The town's news (slice 5a, 2026-11-24):**" in row and "fed to the Mind (§6.6" not in row


PLAN = (OVERLAY / "crates" / "caelza-tools" / "src" / "ether_hollow_plan.rs").read_text()


def test_the_resident_keeps_its_own_hours_in_town():
    """M10 slice 5b: the owner's grid and budget, the agent's own plan inside them, the gateway running it."""
    # The config: the grid and the budget on each resident, carried by the resolver; the tool gets its plan's place.
    files = re.findall(r"^\+\+\+ b/(.+)$", DAY_PLAN_PATCH, flags=re.M)
    assert files == ["crates/caelza-config/src/schema.rs", "crates/caelza-runtime/src/tools/mod.rs", "web/src/lib/i18n.ts"], files
    assert DAY_PLAN_PATCH.count("+    pub hours: Vec<String>,") == 3 and DAY_PLAN_PATCH.count("+    pub visits_month: u64,") == 3
    assert "+            hours: self.hours.clone()," in DAY_PLAN_PATCH and "+            hours: cfg.hours.clone()," in DAY_PLAN_PATCH
    assert "+            visits_month: 0," in DAY_PLAN_PATCH, "the default is no day plan"
    assert ".with_plan(root_config.install_root_dir(), agent_alias, resident.hours.clone(), resident.visits_month)" in DAY_PLAN_PATCH
    removed = [l for l in DAY_PLAN_PATCH.splitlines() if l.startswith("-") and not l.startswith("---")]
    assert len(removed) == 2, removed
    assert MANIFEST["components"]["runtime"]["world_day_plan_patch"] == "runtime/patches/0029-day-plan.patch"
    # The rule: the grid's lines, the budget's unit, the files, what is refused.
    assert '#[path = "ether_hollow_plan.rs"]\npub mod plan;' in TOOL
    assert 'pub const LOCAL_ACTIONS: &[&str] = &["plan"];' in TOOL and "plan" not in rust_str_list(TOOL, "ACTIONS")
    assert "if kind_of(&action) == Kind::Local {" in TOOL, "the plan never reaches the town"
    assert 'pub const DAYS: [&str; 7] = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];' in PLAN
    assert "pub const BUDGET_UNIT: &str = \"planned visits a month" in PLAN
    assert 'root.join(WORLD_DIR).join(PLAN_DIR).join(format!("{}.json", file_alias(alias)))' in PLAN
    assert 'root.join(WORLD_DIR).join(PLAN_DIR).join(format!("{}.used.json", file_alias(alias)))' in PLAN
    for refusal in ("is outside the hours your owner gives you on", "your owner's budget has", "overlap: one place at a time", "is already over", "has not given you hours in town yet"):
        assert refusal in PLAN, refusal
    # The gateway: the planner beside the waker, the visit, the walk, the wake, the count, the memory.
    assert "tokio::spawn(async move { planner_loop(planner_state).await });" in API
    assert "pub const PLAN_TICK: Duration = Duration::from_secs(30);" in API
    assert "enabled && wake && has_key && hours.iter().any(|h| !h.trim().is_empty()) && visits_month > 0" in API
    assert "used.count(&month, Some(plan::slot_key(&day, &slot.at)));" in API, "counted before it runs"
    assert "let g = begin_visit(p, minutes, now_secs());\n            p.plan = Some(running.clone());" in API
    assert 'json!({"action": "move", "to": id})' in API and "plan::match_place(&snapshot, place)" in API
    assert 'json!({"action": "status", "format": "json"})' in API and 'join("IDENTITY.md")' in API
    assert "plan::slot_prompt(&town.name, slot, &end_text, want.as_deref(), moved.as_deref())" in API
    assert "plan::wants_planning(&spans, today, now_min, &plans, &used, town.visits_month)" in API
    assert "pub fn planned_visit_episode(" in API and "My day plan took me to town" in API
    assert '"plan": plan_report(&state, &town),' in API
    # The card: the grid, the budget, today's plan; the client's shape; Home's line.
    for attr in ("data-world-plan ", "data-world-plan-day={d.day}", "data-world-plan-budget", "data-world-plan-used", 'data-world-action="plan"', "data-world-plan-today", "data-world-plan-now"):
        assert attr in DOOR, attr
    assert "await patchConfig(planOps(linesFromGrid(grid), visits, state.plan.path));" in DOOR
    for fn in ("gridFromLines", "linesFromGrid", "gridProblem", "planOps", "budgetOf", "slotLine", "slotState", "planNowLine"):
        assert f"export function {fn}(" in DOOR_LOGIC and f"{fn}(" in DOOR_LOGIC_TEST, fn
    assert "export interface WorldPlan {" in CLIENT and "plan?: WorldPlan;" in CLIENT and "plan?: WorldPlanNow | null;" in CLIENT
    assert "export function planNow(r: TownResidentSlice): string | null {" in HOME_LOGIC
    assert "At the bank: opening the shop, until 10:00" in HOME_LOGIC_TEST
    # The docs, the FAQ and the corpus.
    p5 = " ".join(NOTE.split("**P5 · The town in the Mind, and on Home (Caelza).**", 1)[1].split("**P6 ·", 1)[0].split())
    assert "**The day plan (slice 5b, 2026-11-24):**" in p5 and p5.endswith("Nothing is left in P5.")
    assert "**Done:** the town's news in the Mind (5a, 2026-11-24); the day plan (5b, 2026-11-24, P5 below)." in NOTE
    section = " ".join(FAQ.split("## Can Cael live in Ether Hollow?", 1)[1].split("\n## ", 1)[0].split())
    assert "keep its own hours in town" in section and "one run of the model" in section
    assert "keep its own hours in town" in CORPUS and CORPUS == APP_CORPUS
    row = VISION.split("| **M10 Ether Hollow** |", 1)[1].split("\n", 1)[0]
    assert "**The day plan (slice 5b, 2026-11-24):**" in row and "slice 5's day plan" not in row
