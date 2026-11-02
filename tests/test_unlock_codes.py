"""The Arcade pack and the unlock codes (vision M8, the fifth slice).

A priced pack opens with a code the owner mints (scripts/unlock_codes.py,
Ed25519 in plain Python) and the Runtime checks against the public key baked
into the gateway (api_looks.rs, through rustls' ring provider: nothing new is
linked). These tests pin the Python Ed25519 to RFC 8032, the minted fixture
to the Rust test's constant, the catalog's key to the gateway's, the Shop
and the wardrobe logic to the new path, and patch 0014 to what it claims.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "unlock_codes.py"
CATALOG = json.loads((REPO_ROOT / "looks" / "catalog.json").read_text())
API_RS = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-gateway" / "src" / "api_looks.rs").read_text()
OVERLAY = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (OVERLAY / "looks" / "looks.logic.ts").read_text()
LOGIC_TEST = (OVERLAY / "looks" / "looks.logic.test.ts").read_text()
SHOP = (OVERLAY / "pages" / "Shop.tsx").read_text()
PATCH = (REPO_ROOT / "runtime" / "patches" / "0014-unlock-codes.patch").read_text()
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())
README = (REPO_ROOT / "looks" / "README.md").read_text()

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import unlock_codes as uc  # noqa: E402

TEST_SEED = hashlib.sha256(b"caelza test unlock key").digest()
RUST_TEST_KEY = re.search(r'const TEST_PUBLIC_KEY: &str = "([0-9a-f]{64})";', API_RS).group(1)
RUST_TEST_CODE = re.search(r'const TEST_CODE: &str = "([^"]+)";', API_RS).group(1)
RUST_SHOP_KEY = re.search(r'pub const UNLOCK_PUBLIC_KEY: &str = "([0-9a-f]{64})";', API_RS).group(1)


def test_ed25519_is_rfc_8032():
    # Test vectors 1 and 2 of RFC 8032 §7.1.
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    assert uc.public_key(seed).hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    assert uc.sign(seed, b"").hex() == (
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    seed2 = bytes.fromhex("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb")
    assert uc.public_key(seed2).hex() == "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
    assert uc.sign(seed2, b"\x72").hex() == (
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
    )
    pk = uc.public_key(seed)
    assert uc.verify(pk, b"", uc.sign(seed, b"")) and not uc.verify(pk, b"x", uc.sign(seed, b""))
    assert not uc.verify(pk, b"", b"\x00" * 64) and not uc.verify(pk, b"", b"short") and not uc.verify(b"\x00" * 32, b"", uc.sign(seed, b""))
    cryptography = pytest.importorskip("cryptography")  # the owner's machine needs none of it; here it double-checks
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

    assert cryptography
    assert Ed25519PrivateKey.from_private_bytes(seed2).sign(b"hello") == uc.sign(seed2, b"hello")
    Ed25519PublicKey.from_public_bytes(uc.public_key(seed2)).verify(uc.sign(seed2, b"hello"), b"hello")


def test_the_fixture_the_rust_test_checks_is_what_python_mints():
    assert uc.public_key(TEST_SEED).hex() == RUST_TEST_KEY
    assert uc.mint(TEST_SEED, "arcade", "TEST2345") == RUST_TEST_CODE, "deterministic: the same seed, pack and id give the same code"
    assert uc.check(RUST_TEST_CODE, uc.public_key(TEST_SEED)) == ("arcade", "TEST2345")
    assert uc.check(RUST_TEST_CODE.lower(), uc.public_key(TEST_SEED)) is None, "the signature is case-sensitive, the rest is not"
    assert uc.check(" arcade-test2345-" + RUST_TEST_CODE.split("-", 2)[2] + " ", uc.public_key(TEST_SEED)) == ("arcade", "TEST2345")
    assert uc.check(RUST_TEST_CODE, bytes.fromhex(RUST_SHOP_KEY)) is None, "the test key is not the shop's"
    assert uc.check(RUST_TEST_CODE.replace("ARCADE", "COSMIC", 1), uc.public_key(TEST_SEED)) is None
    assert uc.check(RUST_TEST_CODE.replace("TEST2345", "TEST2346", 1), uc.public_key(TEST_SEED)) is None
    for bad in ("", "ARCADE", "ARCADE-TEST2345", "ARCADE-TEST2345-short", "ARCADE-TEST0345-" + RUST_TEST_CODE.split("-", 2)[2], "A" * 200):
        assert uc.parse(bad) is None, bad
    # The last character carries padding bits: a non-canonical one is refused here as the Runtime refuses it.
    tail = RUST_TEST_CODE[:-1] + ("h" if RUST_TEST_CODE[-1] != "h" else "g")
    assert uc.parse(tail) is None and uc.check(tail, uc.public_key(TEST_SEED)) is None
    assert 'assert_eq!(parse_code(&tail).unwrap_err(), "not an unlock code"' in API_RS
    minted = {uc.mint(TEST_SEED, "arcade") for _ in range(5)}
    assert len(minted) == 5 and all(uc.check(c, uc.public_key(TEST_SEED))[0] == "arcade" for c in minted)
    assert all(ch in uc.ID_ALPHABET for c in minted for ch in c.split("-")[1]) and "O" not in uc.ID_ALPHABET and "0" not in uc.ID_ALPHABET
    with pytest.raises(ValueError):
        uc.mint(TEST_SEED, "no-hyphens")
    # The Rust side reads the same fixture and the same rules.
    assert 'assert_eq!(verify_code(TEST_CODE, TEST_PUBLIC_KEY).expect("good"), ("arcade".to_string(), "TEST2345".to_string()));' in API_RS
    assert 'const UNLOCK_MESSAGE_PREFIX: &str = "caelza-unlock:v1:";' in API_RS and uc.MESSAGE_PREFIX == "caelza-unlock:v1:"
    assert 'const CODE_ID_ALPHABET: &str = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ";' in API_RS and uc.ID_ALPHABET == "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def test_the_shops_key_is_one_key_in_the_catalog_and_the_gateway():
    unlock = CATALOG["unlock"]
    assert unlock["scheme"] == uc.SCHEME == "ed25519-v1"
    assert unlock["public_key"] == RUST_SHOP_KEY
    assert uc.catalog_public_key().hex() == RUST_SHOP_KEY
    assert "rustls::crypto::ring::default_provider()" in API_RS, "Ed25519 through the TLS stack already linked"
    assert "ed25519" not in (REPO_ROOT / "runtime" / "patches" / "0014-unlock-codes.patch").read_text().lower(), "no new crate: the lock file stays"
    arcade = next(p for p in CATALOG["packs"] if p["id"] == "arcade")
    assert arcade["status"] == "available" and arcade["price"] == {"usd": 3} and arcade["unlock"] == "code"
    arcade_parts = [p for p in CATALOG["parts"] if p["pack"] == "arcade"]
    assert {p["layer"] for p in arcade_parts} == {"backdrop", "outfit", "hair", "hat", "face", "accessory"}
    assert len(arcade_parts) >= 7
    sheet = REPO_ROOT / "runtime" / "overlay" / "web" / "public" / "looks" / "sheets" / "arcade.png"
    assert sheet.is_file() and sheet.stat().st_size > 2000


def test_a_pack_id_is_one_word_so_a_code_can_name_it():
    pytest.importorskip("PIL")
    sys.path.insert(0, str(REPO_ROOT / "looks"))
    import looks as cli

    catalog = json.loads(json.dumps(CATALOG))
    catalog["packs"].append({"id": "neon-nights", "name": "Neon", "blurb": "", "price": {"usd": 2}, "status": "soon", "unlock": "code"})
    problems = cli.check(catalog)
    assert any("'neon-nights'" in p and "no hyphen" in p for p in problems), problems
    assert all("arcade" not in p for p in problems)
    with pytest.raises(ValueError):
        uc.mint(TEST_SEED, "neon-nights")


def test_the_cli_mints_and_verifies_and_keeps_the_key_private(tmp_path: Path):
    key = tmp_path / "keys" / "unlock.key"
    out = subprocess.run([sys.executable, "-I", str(SCRIPT), "keygen", "--out", str(key)], capture_output=True, text=True, check=True)
    assert "public key: " in out.stdout
    assert stat.S_IMODE(key.stat().st_mode) == 0o600
    with pytest.raises(FileExistsError):
        uc.write_seed(key, os.urandom(32))
    pk = subprocess.run([sys.executable, "-I", str(SCRIPT), "public-key", "--key", str(key)], capture_output=True, text=True, check=True).stdout.strip()
    assert pk == out.stdout.split("public key: ")[1].split()[0]
    codes = subprocess.run([sys.executable, "-I", str(SCRIPT), "mint", "--key", str(key), "--pack", "arcade", "--count", "3"], capture_output=True, text=True, check=True).stdout.split()
    assert len(codes) == 3 and all(c.startswith("ARCADE-") for c in codes)
    # verify reads the catalog's key: the shop's key says no to this key's codes, a catalog carrying this key says yes.
    no = subprocess.run([sys.executable, "-I", str(SCRIPT), "verify", codes[0]], capture_output=True, text=True)
    assert no.returncode == 1 and "not a good code" in no.stderr
    catalog = dict(CATALOG)
    catalog["unlock"] = {"scheme": uc.SCHEME, "public_key": pk}
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    yes = subprocess.run([sys.executable, "-I", str(SCRIPT), "verify", codes[0], "--catalog", str(tmp_path / "catalog.json")], capture_output=True, text=True)
    assert yes.returncode == 0 and yes.stdout.strip() == f"ok: unlocks the arcade pack (code {codes[0].split('-')[1]})"


def test_the_wardrobe_remembers_an_unlock_and_the_shop_asks_for_a_code():
    assert "pub async fn handle_wardrobe_unlock(" in API_RS
    assert 'wardrobe["unlocks"] = stored["unlocks"].clone()' in API_RS, "PUT cannot add or drop an unlock"
    assert 'unlocks.insert(pack.clone(), Value::String(id));' in API_RS
    assert "export function parseUnlockCode(" in LOGIC and "export function unlocked(" in LOGIC and "export function isPriced(" in LOGIC
    assert "if (isPriced(pack) && !unlocked(pack.id, wardrobe)) continue;" in LOGIC, "a priced pack in the wardrobe is worn only once opened"
    assert "an unlock code's shape" in LOGIC_TEST and "TEST2345" in LOGIC_TEST
    assert "setWardrobe(await unlockPack(code));" in SHOP and "parseUnlockCode(code)" in SHOP
    assert "isPriced(pack) && !unlocked(pack.id, wardrobe)" in SHOP, "opened before: one tap, no code"
    for key in ('t("shop.code_bad")', 't("shop.code_other_pack")', 't("shop.unlocked")', 't("shop.unlock")', 't("shop.unlocking")', 't("shop.code_hint")', 't("shop.get_code")'):
        assert key in SHOP, key
    assert "shop.codes_soon" not in SHOP


def test_patch_touches_only_the_files_it_claims():
    touched = sorted({line.split()[1][2:] for line in PATCH.splitlines() if line.startswith("+++ b/")})
    assert touched == ["crates/caelza-gateway/src/lib.rs", "web/src/lib/api.ts", "web/src/lib/i18n.ts"]
    assert '+        .route("/api/looks/wardrobe/unlock", post(api_looks::handle_wardrobe_unlock))' in PATCH
    assert "+export function unlockPack(code: string): Promise<Wardrobe> {" in PATCH
    assert '-    \'shop.codes_soon\': "codes arrive with the first priced pack",' in PATCH
    added = dict(re.findall(r"^\+    '(shop\.[a-z_]+)': (.*),$", PATCH, re.M))
    assert set(added) == {"shop.code_bad", "shop.code_hint", "shop.code_other_pack", "shop.get_code", "shop.retry", "shop.unlock", "shop.unlocked", "shop.unlocking"}
    assert "+    'looks.wardrobe_failed': " in PATCH
    assert "{pack}" in added["shop.code_other_pack"]
    rt = MANIFEST["components"]["runtime"]
    assert rt["unlock_codes"] == "scripts/unlock_codes.py" and rt["unlock_patch"] == "runtime/patches/0014-unlock-codes.patch"
    assert (REPO_ROOT / rt["unlock_codes"]).is_file() and (REPO_ROOT / rt["unlock_patch"]).is_file()
    assert "unlock_codes.py keygen" in README and "UNLOCK_PUBLIC_KEY" in README
