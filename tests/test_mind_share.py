"""One Mind for every device: the Memory page's devices cards.

The device that runs the Mind shares it (its address into the service's
config.json, a `caelza-share` token into its tokens.json as a hash, a join
code), the other device joins with the code (the gateway probes, the page
writes the config through the upstream API). These tests keep the gateway
module, the patch, the page, its logic, the client and the docs saying the
same thing; the module's own behaviour is under `cargo test -p caelza-gateway
api_mind_share`, the page's pure part under the web test list.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OVERLAY = REPO_ROOT / "runtime" / "overlay"
GATEWAY = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_mind_share.rs").read_text()
API_MIND = (OVERLAY / "crates" / "caelza-gateway" / "src" / "api_mind.rs").read_text()
XANIMA_RS = (OVERLAY / "crates" / "caelza-memory" / "src" / "xanima.rs").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0016-mind-share.patch").read_text()
PAGE = (OVERLAY / "web" / "src" / "pages" / "Memory.tsx").read_text()
LOGIC = (OVERLAY / "web" / "src" / "pages" / "mind.share.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "web" / "src" / "pages" / "mind.share.logic.test.ts").read_text()
CLIENT = (OVERLAY / "web" / "src" / "lib" / "mind.ts").read_text()
README = (REPO_ROOT / "README.md").read_text()
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text()
MIND_README = (REPO_ROOT / "mind" / "README.md").read_text()
VISION = (REPO_ROOT / "docs" / "design" / "caelza-vision.md").read_text()
CORPUS = (REPO_ROOT / "guide" / "corpus.jsonl").read_text()


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def test_the_patch_registers_the_module_its_routes_the_test_and_caels_sentence():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    assert files == ["crates/caelza-gateway/src/lib.rs", "web/package.json", "web/src/lib/i18n.ts"], files
    assert "+pub mod api_mind_share;" in PATCH
    for line in (
        '+        .route(',
        '+            "/api/mind/share",',
        '+            get(api_mind_share::handle_share_get)',
        '+                .post(api_mind_share::handle_share_post)',
        '+                .delete(api_mind_share::handle_share_delete),',
        '+        )',
        '+        .route("/api/mind/probe", post(api_mind_share::handle_probe))',
    ):
        assert f"\n{line}\n" in PATCH, line
    # The test joins the list beside the Mind page's; one line leaves, one comes.
    removed = [l for l in PATCH.splitlines() if l.startswith('-    "test":')]
    added = [l for l in PATCH.splitlines() if l.startswith('+    "test":')]
    assert len(removed) == 1 and len(added) == 1
    assert "src/pages/mind.logic.test.ts src/pages/mind.share.logic.test.ts " in added[0]
    assert added[0].replace("src/pages/mind.share.logic.test.ts ", "") == "+" + removed[0][1:], "only the one test joins the list"
    # Cael's Memory screen sentence: only that one string changes in i18n.ts.
    i18n_hunk = PATCH.split("+++ b/web/src/lib/i18n.ts")[1]
    assert i18n_hunk.count("\n-    'guide.screen_memory'") == 1 and i18n_hunk.count("\n+    'guide.screen_memory'") == 1
    assert "Under Your other devices you can share this Mind with your phone, or join the one on your PC" in i18n_hunk


def test_the_gateway_follows_the_services_own_rules():
    # The service's files, found the way the service finds them.
    assert 'std::env::var("XANIMA_SERVICE_ROOT")' in GATEWAY
    assert 'let neu = home.join(".xanima");' in GATEWAY and 'data.join("service")' in GATEWAY
    # tailnetHosts is the service's one non-wildcard way to add a listener; 127.0.0.1 is always there.
    assert 'cfg.get("tailnetHosts")' in GATEWAY
    assert "the Mind already listens on 127.0.0.1" in GATEWAY
    # Never a public address, never a wildcard, never a name.
    assert 'if kind_of(ip) == "public" {' in GATEWAY and "whole internet" in GATEWAY
    assert "ip.is_unspecified() || ip.is_multicast()" in GATEWAY
    assert "only IP literals" in GATEWAY.lower() or "names are not accepted" in GATEWAY
    # Tailscale's range, the private ranges.
    assert "o[0] == 100 && (64..128).contains(&o[1])" in GATEWAY
    assert "v4.is_private() || v4.is_link_local()" in GATEWAY
    # Tokens: the service's prefix, its hash form, its id form, its scopes; never a plaintext field.
    assert 'const TOKEN_PREFIX: &str = "swt_";' in GATEWAY
    assert 'format!("sha256:{}", hex::encode(Sha256::digest(token.as_bytes())))' in GATEWAY
    assert 'format!("tok_{}", &uuid::Uuid::new_v4().simple().to_string()[..12])' in GATEWAY
    assert 'const SHARE_SCOPES: [&str; 2] = ["read", "write"];' in GATEWAY
    assert 'if t.get("token").is_some() {' in GATEWAY and "refusing to touch it" in GATEWAY
    assert "write_json(tokens_path, &file, true)" in GATEWAY, "the token file is written owner-only"
    # Revocation is by label, the way DELETE promises.
    assert 'const SHARE_LABEL: &str = "caelza-share";' in GATEWAY
    assert 'obj.insert("revoked".to_string(), json!(true));' in GATEWAY
    # Provisioning stays off on the joining side; the probe checks health, then the token.
    assert "settings.provision_token_file = None;" in GATEWAY
    assert '"brain_stats", json!({"visibility": "all", "format": "json"})' in GATEWAY
    assert "did not accept this code" in GATEWAY
    # Every route is behind the dashboard's auth.
    assert GATEWAY.count("require_auth(&state, &headers)") == 4
    # The health probe the module leans on lives in the memory backend.
    assert "pub async fn health_info(&self) -> Result<Value>" in XANIMA_RS
    assert 'let url = format!("{}/health", self.settings.url);' in XANIMA_RS
    # Share and stop only from the device that hosts the Mind.
    assert "share from the device that runs it" in GATEWAY
    assert "pub(crate) fn mind_wiring" in API_MIND and "use super::api_mind::{MindWiring, mind_wiring};" in GATEWAY


def test_the_bug_check_fixes_hold():
    # A non-ASCII prefix is an error, not a panic (no split_at on a byte index).
    assert "split_at(" not in GATEWAY and ".get(..CODE_PREFIX.len())" in GATEWAY
    # Stop sharing revokes before it clears the address.
    delete = GATEWAY.split("pub async fn handle_share_delete")[1].split("pub struct ProbeBody")[0]
    assert delete.index("revoke_share_tokens(&paths.tokens)") < delete.index("without_hosts(&mut cfg)")
    # The service's files the way the service finds them; sharing never creates a root.
    assert "pub fn service_root_for(env_root: Option<&str>, home: Option<&Path>) -> PathBuf" in GATEWAY
    assert '.join(".sharpwave")' in GATEWAY and 'std::env::var_os("XANIMA_HOME_OVERRIDE")' in GATEWAY
    assert 'c.get("tokensFile")' in GATEWAY and "if !mind_installed(&paths) {" in GATEWAY
    # Only this machine's addresses; IPv6 listeners matched by (ip, port); reserved agent names refused.
    assert "own_address(ip, &candidates())" in GATEWAY and "pub fn parse_listener(entry: &str)" in GATEWAY
    assert 'matches!(agent.to_ascii_lowercase().as_str(), "shared" | "_system" | "backups" | "audit")' in GATEWAY
    # The probe follows no code that points off the home network.
    assert "that code points at an internet address" in GATEWAY and "by a name, not an address" in GATEWAY
    # The joined device leaves backend-first and probes the default port for its own Mind.
    assert PAGE.index("await patchConfig(leaveBackendOps(localMind));") < PAGE.index("await deleteMapKey(STORAGE_PATH, STORAGE_KEY);")
    assert '"local_mind": local_mind_up(DEFAULT_PORT).await' in GATEWAY
    # Live codes are shown, and revocable, whether or not an address is shared.
    assert 'data-mind-share="revoke"' in PAGE
    assert "export function parseListener(entry: string)" in LOGIC
    # The copy says what plain HTTP on home Wi-Fi means.
    assert "On home Wi-Fi the link is not encrypted" in PAGE and "not encrypted" in squash(FAQ)
    assert "a code that points at an internet address is\nrefused" in FAQ or "internet address is refused" in squash(FAQ)


def test_the_join_code_is_one_string_with_a_prefix():
    assert 'pub const CODE_PREFIX: &str = "caelza-mind:";' in GATEWAY
    assert "URL_SAFE_NO_PAD.encode(body)" in GATEWAY
    assert ".or_else(|_| URL_SAFE.decode(body))" in GATEWAY, "a padded copy decodes too"
    assert 'placeholder="caelza-mind:…"' in PAGE
    assert "export function cleanCode(raw: string): string {\n  return raw.replace(/\\s+/g, '');" in LOGIC


def test_the_page_shows_one_card_per_role_and_writes_the_config_the_upstream_way():
    assert "<ShareCard onAction={() => onNote(null)} />" in PAGE
    assert "<JoinedCard url={status.url ?? ''} onNote={onNote} onChanged={onChanged} />" in PAGE
    assert "<JoinCard onNote={onNote} onChanged={onChanged} />" in PAGE
    assert 'data-mind-devices={role}' in PAGE
    # Joining: probe first, then the row by name, then one atomic patch; the token comes back from the probe.
    assert "const probe = await probeMindCode(clean);" in PAGE
    assert "await createMapKey(STORAGE_PATH, STORAGE_KEY);" in PAGE
    assert "await patchConfig(joinOps(probe.url, probe.token, probe.agent));" in PAGE
    assert "export const STORAGE_PATH = 'storage.xanima';" in LOGIC and "export const STORAGE_KEY = 'default';" in LOGIC
    for path in ("/url", "/token", "/agent", "/provision_token_file"):
        assert f"path: `${{PREFIX}}{path}`" in LOGIC, path
    assert "{ op: 'add', path: '/memory/backend', value: 'xanima' }" in LOGIC
    # Leaving: the row goes (the token with it), then the backend.
    assert "await deleteMapKey(STORAGE_PATH, STORAGE_KEY);" in PAGE
    assert "await patchConfig(leaveBackendOps(localMind));" in PAGE
    assert "export const FALLBACK_BACKEND = 'sqlite';" in LOGIC
    # The devices card is there with the Mind off (that is when a phone joins) and on.
    assert PAGE.count("<Devices status={status} note={devicesNote} onNote={setDevicesNote} onChanged={refresh} />") == 2
    # Both restart notes exist and the host one covers Windows' firewall question.
    assert "Restart the Mind once" in LOGIC and "Node.js" in LOGIC
    assert "Reload daemon" in LOGIC and "Stop, then Start" in LOGIC
    # The joined and left notes live on the page, not in the card that is replaced on the next status read.
    assert "const [devicesNote, setDevicesNote] = useState<string | null>(null);" in PAGE
    assert PAGE.count("onNote(") >= 2 and 'data-mind-share="note"' in PAGE
    # The code box selects on focus and copies; the page never shows a token anywhere else.
    assert 'data-mind-share="code"' in PAGE and "navigator.clipboard.writeText(code)" in PAGE
    assert "probe.token" in PAGE and PAGE.replace("share_tokens", "").count("token") < 12


def test_the_client_matches_the_routes():
    assert "apiFetch<MindShareState>('/api/mind/share')" in CLIENT
    assert "apiFetch<MindShareResult>('/api/mind/share', { method: 'POST', body: JSON.stringify({ host }) })" in CLIENT
    assert "apiFetch<MindUnshareResult>('/api/mind/share', { method: 'DELETE' })" in CLIENT
    assert "apiFetch<MindProbeResult>('/api/mind/probe', { method: 'POST', body: JSON.stringify({ code }) })" in CLIENT
    for field in ("configured?: string[];", "listening?: string[];", "candidates?: MindShareCandidate[];", "local_mind?: boolean;", "token: string;"):
        assert field in CLIENT, field


def test_the_logic_test_covers_what_the_page_leans_on():
    for name in ("devicesRole", "joinOps", "leaveBackendOps", "isListening", "preferredCandidate", "cleanCode", "restartNote"):
        assert f"{name}(" in LOGIC_TEST, name


def test_the_docs_tell_the_owner_the_same_story():
    faq = squash(FAQ)
    assert "## Can Cael remember on my PC and my phone?" in FAQ
    assert "Your other devices" in faq and "Join a Mind on another device" in faq
    assert "Stop sharing" in faq and "Use this device's own memory" in faq
    assert "never on the open internet" in faq and "Tailscale encrypts it" in faq
    assert "Share** the Mind under *Your other devices*" in README
    assert "One Mind for every device: shipped" in MIND_README
    assert "tailnetHosts" in MIND_README and "caelza-share" in MIND_README
    assert "**One Mind for every device (plan, this PR):**" not in VISION, "the vision row says shipped, not planned"
    assert "**Shipped (one Mind for every device):**" in VISION and "api_mind_share.rs" in VISION
    # Cael answers from the FAQ: the entry is in his corpus.
    entries = [json.loads(line) for line in CORPUS.splitlines() if line.strip()]
    assert any("Can Cael remember on my PC and my phone?" in (e.get("title") or e.get("heading") or "") or "Can Cael remember on my PC and my phone" in json.dumps(e) for e in entries)
