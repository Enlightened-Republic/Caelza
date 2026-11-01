"""The app's gateway behind pairing (android-app.md §2; the §6 "loopback exposure" item closed).

The app writes `require_pairing = true`, pairs its own shell with the gateway's
admin token (GatewayPairing.kt) and hands the token to the dashboard. These
tests pin the Kotlin constants against the Runtime's pairing module and the
dashboard's auth module when the staged tree is here, and the docs.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
APP = REPO_ROOT / "android" / "app"
KT = APP / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza"
PAIRING = (KT / "runtime" / "GatewayPairing.kt").read_text()
STORE = (KT / "runtime" / "RuntimeStore.kt").read_text()
MAIN = (KT / "MainActivity.kt").read_text()
SERVICE = (KT / "RuntimeService.kt").read_text()
STAGED = REPO_ROOT / "runtime" / ".build" / "src"


def test_the_app_keeps_pairing_on_and_turns_it_on_for_an_older_config():
    default_config = re.search(r'val DEFAULT_CONFIG = """(.*?)""".trimMargin\(\)', STORE, re.S).group(1)
    assert "require_pairing = true" in default_config and "require_pairing = false" not in default_config
    assert "ensurePairingOn(config)" in STORE
    assert re.search(r'PAIRING_OFF = Regex\("""\^\(\[ \\t\]\*\)require_pairing\\s\*=\\s\*false', STORE), "the migration matches the line the old default wrote"


def test_the_pairing_constants_are_the_runtimes():
    assert 'const val DATA_DIR = "data"' in PAIRING
    assert 'const val ADMIN_TOKEN_FILE = "gateway-admin.token"' in PAIRING
    assert 'const val ADMIN_TOKEN_HEADER = "x-caelza-admin-token"' in PAIRING
    assert 'const val WEB_TOKEN_KEY = "caelza_token"' in PAIRING
    assert '"$base/admin/paircode/new"' in PAIRING and '"$base/api/pair"' in PAIRING and '"$base/api/status"' in PAIRING
    assert '"pairing_code"' in PAIRING and '"token"' in PAIRING and '"pairing_required"' in PAIRING
    if not STAGED.is_dir():
        pytest.skip("the Runtime is not staged here")
    pairing_rs = (STAGED / "crates" / "caelza-config" / "src" / "pairing.rs").read_text()
    assert 'GATEWAY_ADMIN_TOKEN_HEADER: &str = "x-caelza-admin-token"' in pairing_rs
    assert 'GATEWAY_ADMIN_TOKEN_FILE: &str = "gateway-admin.token"' in pairing_rs
    schema_rs = (STAGED / "crates" / "caelza-config" / "src" / "schema.rs").read_text()
    assert 'config_dir.join("data")' in schema_rs, "the gateway's data dir is <config dir>/data"
    auth_ts = (STAGED / "web" / "src" / "lib" / "auth.ts").read_text()
    assert "const TOKEN_KEY = 'caelza_token';" in auth_ts
    gateway_rs = (STAGED / "crates" / "caelza-gateway" / "src" / "lib.rs").read_text()
    assert '.route("/admin/paircode/new", post(handle_admin_paircode_new))' in gateway_rs
    assert '.route("/api/pair", post(api_pairing::submit_pairing_enhanced))' in gateway_rs


def test_the_shell_hands_the_token_to_the_dashboard_and_the_service_sends_it():
    assert "GatewayPairing.forStore(store).ensureToken(port)" in MAIN
    assert "GatewayPairing.tokenScript(" in MAIN and 'Gateway.url(port, "/health")' in MAIN, "the handoff page is /health on the gateway's origin"
    assert "GatewayPairing.forStore(store).ensureToken(port)" in SERVICE
    assert "CaelCorpus(store.configDir).load(jsonl, port, token)" in SERVICE
    corpus = (KT / "guide" / "CaelCorpus.kt").read_text()
    assert 'conn.setRequestProperty("Authorization", "Bearer $token")' in corpus


def test_the_docs_say_so():
    design = (REPO_ROOT / "docs" / "design" / "android-app.md").read_text()
    assert "Loopback exposure" not in design and "require_pairing = true" in design and "GatewayPairing.kt" in design
    assert "pairing off" not in (REPO_ROOT / "android" / "README.md").read_text()
    faq = (REPO_ROOT / "guide" / "FAQ.md").read_text()
    assert "pairs its own dashboard shell" in faq and "pairing off" not in faq
    manifest = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
    assert manifest["android"]["gateway_pairing"].endswith("GatewayPairing.kt")
