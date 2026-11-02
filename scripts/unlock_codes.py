#!/usr/bin/env python3
"""Unlock codes for the Shop's priced packs (vision M8).

    python3 scripts/unlock_codes.py keygen --out ~/.caelza-keys/unlock.key   # a new signing key; prints the public key
    python3 scripts/unlock_codes.py mint --key ~/.caelza-keys/unlock.key --pack arcade --count 5
    python3 scripts/unlock_codes.py verify ARCADE-7K3PQ2M9-...                 # against the public key in looks/catalog.json

A code is `<PACK>-<ID>-<SIGNATURE>`: the pack id, eight characters that make
the code its own, and an Ed25519 signature (base64url, no padding) over
`caelza-unlock:v1:<pack>:<id>` by the signing key the owner keeps. The
Runtime verifies a code with the public key baked into the gateway
(api_looks.rs `UNLOCK_PUBLIC_KEY`, the same hex as `unlock.public_key` in
looks/catalog.json) and records the unlock in the wardrobe. Nothing but the
public key ships, so a code cannot be minted from the app; it can only be
checked.

Ed25519 is RFC 8032 in plain Python below (slow, a few milliseconds a code,
and nothing to install), pinned to the RFC's test vectors and to the Rust
side by tests/test_unlock_codes.py. A code is cosmetic: this is an honest
storefront, not DRM.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "looks" / "catalog.json"

SCHEME = "ed25519-v1"
MESSAGE_PREFIX = "caelza-unlock:v1:"
#: The characters of a code id: no 0/O or 1/I to confuse.
ID_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
ID_LENGTH = 8

# ---- Ed25519 (RFC 8032 §5.1) ----------------------------------------------------

_P = 2**255 - 19
_Q = 2**252 + 27742317777372353535851937790883648493


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


_D = (-121665 * _inv(121666)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = (4 * _inv(5)) % _P
_BX = _xrecover(_BY)
_B = (_BX, _BY, 1, (_BX * _BY) % _P)
_IDENTITY = (0, 1, 1, 0)

Point = tuple[int, int, int, int]


def _add(a: Point, b: Point) -> Point:
    (x1, y1, z1, t1), (x2, y2, z2, t2) = a, b
    aa = (y1 - x1) * (y2 - x2) % _P
    bb = (y1 + x1) * (y2 + x2) % _P
    cc = t1 * 2 * _D * t2 % _P
    dd = z1 * 2 * z2 % _P
    e, f, g, h = bb - aa, dd - cc, dd + cc, bb + aa
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _mul(point: Point, e: int) -> Point:
    out = _IDENTITY
    while e:
        if e & 1:
            out = _add(out, point)
        point = _add(point, point)
        e >>= 1
    return out


def _affine(point: Point) -> tuple[int, int]:
    x, y, z, _t = point
    zi = _inv(z)
    return (x * zi % _P, y * zi % _P)


def _encode(point: Point) -> bytes:
    x, y = _affine(point)
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decode(data: bytes) -> Point:
    if len(data) != 32:
        raise ValueError("a point is 32 bytes")
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        raise ValueError("not a point")
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _P != 0:
        raise ValueError("not on the curve")
    return (x, y, 1, x * y % _P)


def _sha512(*parts: bytes) -> bytes:
    return hashlib.sha512(b"".join(parts)).digest()


def _scalar(h: bytes) -> int:
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a


def public_key(seed: bytes) -> bytes:
    """The 32-byte public key of a 32-byte seed."""
    if len(seed) != 32:
        raise ValueError("a seed is 32 bytes")
    return _encode(_mul(_B, _scalar(_sha512(seed))))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of `message` by the key of `seed` (deterministic)."""
    h = _sha512(seed)
    a = _scalar(h)
    pk = _encode(_mul(_B, a))
    r = int.from_bytes(_sha512(h[32:], message), "little") % _Q
    big_r = _encode(_mul(_B, r))
    k = int.from_bytes(_sha512(big_r, pk, message), "little") % _Q
    s = (r + k * a) % _Q
    return big_r + int.to_bytes(s, 32, "little")


def verify(pk: bytes, message: bytes, signature: bytes) -> bool:
    """True when `signature` is `message` signed by the key behind `pk`."""
    if len(signature) != 64 or len(pk) != 32:
        return False
    try:
        a_point = _decode(pk)
        r_point = _decode(signature[:32])
    except ValueError:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    k = int.from_bytes(_sha512(signature[:32], pk, message), "little") % _Q
    return _affine(_mul(_B, s)) == _affine(_add(r_point, _mul(a_point, k)))


# ---- codes -----------------------------------------------------------------------


def pack_ok(pack: str) -> bool:
    return 0 < len(pack) <= 32 and all(ch.isascii() and (ch.isalnum() or ch in "_-") for ch in pack) and "-" not in pack


def message_for(pack: str, code_id: str) -> bytes:
    return f"{MESSAGE_PREFIX}{pack}:{code_id}".encode("ascii")


def new_id() -> str:
    return "".join(secrets.choice(ID_ALPHABET) for _ in range(ID_LENGTH))


def mint(seed: bytes, pack: str, code_id: str | None = None) -> str:
    """One code for `pack`: `<PACK>-<ID>-<signature>`."""
    pack = pack.lower()
    if not pack_ok(pack):
        raise ValueError(f"{pack!r} is not a pack id")
    code_id = (code_id or new_id()).upper()
    if len(code_id) != ID_LENGTH or any(ch not in ID_ALPHABET for ch in code_id):
        raise ValueError(f"{code_id!r} is not a code id")
    signature = sign(seed, message_for(pack, code_id))
    return f"{pack.upper()}-{code_id}-{base64.urlsafe_b64encode(signature).rstrip(b'=').decode('ascii')}"


def parse(code: str) -> tuple[str, str, bytes] | None:
    """(pack, id, signature) of a code, or None when it is not shaped like one."""
    text = "".join(code.split())
    parts = text.split("-", 2)
    if len(parts) != 3:
        return None
    pack, code_id, sig_text = parts[0].lower(), parts[1].upper(), parts[2]
    if not pack_ok(pack) or len(code_id) != ID_LENGTH or any(ch not in ID_ALPHABET for ch in code_id):
        return None
    if len(sig_text) != 86 or any(not (ch.isascii() and (ch.isalnum() or ch in "-_")) for ch in sig_text):
        return None
    try:
        signature = base64.urlsafe_b64decode(sig_text + "==")
    except (ValueError, base64.binascii.Error):  # type: ignore[attr-defined]
        return None
    if len(signature) != 64:
        return None
    return pack, code_id, signature


def check(code: str, pk: bytes) -> tuple[str, str] | None:
    """(pack, id) of a good code under `pk`, else None."""
    parsed = parse(code)
    if parsed is None:
        return None
    pack, code_id, signature = parsed
    return (pack, code_id) if verify(pk, message_for(pack, code_id), signature) else None


# ---- keys and the catalog -----------------------------------------------------------


def read_seed(path: Path) -> bytes:
    seed = bytes.fromhex(path.read_text(encoding="utf-8").strip())
    if len(seed) != 32:
        raise ValueError(f"{path}: a signing key is 64 hex characters")
    return seed


def write_seed(path: Path, seed: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(seed.hex() + "\n")


def catalog_public_key(path: Path = CATALOG) -> bytes:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    unlock = catalog.get("unlock") or {}
    if unlock.get("scheme") != SCHEME:
        raise ValueError(f"{path}: unlock.scheme is not {SCHEME}")
    pk = bytes.fromhex(unlock["public_key"])
    if len(pk) != 32:
        raise ValueError(f"{path}: unlock.public_key is not 32 bytes")
    return pk


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    kg = sub.add_parser("keygen", help="a new signing key, kept out of the repo; prints the public key for the catalog and the gateway")
    kg.add_argument("--out", type=Path, required=True)
    mt = sub.add_parser("mint", help="codes for a pack")
    mt.add_argument("--key", type=Path, required=True)
    mt.add_argument("--pack", required=True)
    mt.add_argument("--count", type=int, default=1)
    vf = sub.add_parser("verify", help="check a code against the catalog's public key")
    vf.add_argument("code")
    vf.add_argument("--catalog", type=Path, default=CATALOG)
    pk_cmd = sub.add_parser("public-key", help="the public key of a signing key")
    pk_cmd.add_argument("--key", type=Path, required=True)
    args = ap.parse_args(argv)

    if args.cmd == "keygen":
        seed = secrets.token_bytes(32)
        write_seed(args.out, seed)
        print(f"signing key written to {args.out} (keep it out of the repo; mode 600)")
        print(f"public key: {public_key(seed).hex()}")
        print("put the public key in looks/catalog.json (unlock.public_key) and api_looks.rs (UNLOCK_PUBLIC_KEY)")
        return 0
    if args.cmd == "public-key":
        print(public_key(read_seed(args.key)).hex())
        return 0
    if args.cmd == "mint":
        seed = read_seed(args.key)
        for _ in range(max(1, args.count)):
            print(mint(seed, args.pack))
        return 0
    found = check(args.code, catalog_public_key(args.catalog))
    if found is None:
        print("not a good code", file=sys.stderr)
        return 1
    print(f"ok: unlocks the {found[0]} pack (code {found[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
