#!/usr/bin/env python3
"""The curated model catalog behind the simplified setup: bundle/models.json.

The dashboard's /setup and the Android app's first run spin the same wheels
(the providers most people bring a key for, and for each the picks Cael pins
at the top of the model wheel), so the file has one shape and one checker:

    python3 scripts/model_catalog.py check                # the shape, offline
    python3 scripts/model_catalog.py check --online       # ... and every model id against models.dev
    python3 scripts/model_catalog.py check --models-dev api.json
    python3 scripts/model_catalog.py sync                 # copy it into the app's assets

`check` exits 1 with one line per problem. Model ids are checked against the
models.dev catalog the Runtime itself reads (`crates/caelza-providers/src/
models_dev.rs`), under the provider's `models_dev` key when it differs from
the Runtime's kind (the Runtime says `gemini`, models.dev says `google`).
Stdlib only, so it runs where the tests run and in CI.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = REPO_ROOT / "bundle" / "models.json"
ANDROID_ASSET = REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "models.json"
MODELS_DEV_URL = "https://models.dev/api.json"

#: The tags a pick can carry, in the order the wheel shows them. The dashboard
#: (setup.logic.ts) and the app (ModelCatalog.kt) name the same four.
TAGS = ("best", "fast", "strong", "free")

#: One `best` per provider: it is the row the wheel rests on.
REQUIRED_TAGS = ("best",)

_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
_KIND = re.compile(r"^[a-z][a-z0-9_]*$")


def load(path: Path = CATALOG) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def check(catalog: dict) -> list[str]:
    """The shape: every problem as one line, empty when the file is good."""
    problems: list[str] = []
    if catalog.get("version") != 1:
        problems.append("version must be 1")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(catalog.get("updated", ""))):
        problems.append("updated must be a YYYY-MM-DD date")
    tags = catalog.get("tags")
    if not isinstance(tags, dict) or tuple(tags) != TAGS:
        problems.append(f"tags must name exactly {list(TAGS)} in that order")
    providers = catalog.get("providers")
    if not isinstance(providers, list) or not providers:
        return problems + ["providers must be a non-empty list"]
    seen_kinds: set[str] = set()
    for i, p in enumerate(providers):
        where = f"providers[{i}]"
        if not isinstance(p, dict):
            problems.append(f"{where}: must be an object, not {type(p).__name__}")
            continue
        kind = p.get("id")
        if not isinstance(kind, str) or not _KIND.match(kind):
            problems.append(f"{where}: id must be the Runtime's provider kind (lowercase, underscores)")
            kind = str(kind)
        where = f"provider {kind}"
        if kind in seen_kinds:
            problems.append(f"{where}: listed twice")
        seen_kinds.add(kind)
        if not isinstance(p.get("label"), str) or not p["label"].strip():
            problems.append(f"{where}: label is required")
        if "models_dev" in p and (not isinstance(p["models_dev"], str) or not p["models_dev"]):
            problems.append(f"{where}: models_dev must be the models.dev provider key when given")
        if not isinstance(p.get("key_prefix"), str):
            problems.append(f"{where}: key_prefix must be a string (empty when keys have no fixed start)")
        page = p.get("key_page")
        if not isinstance(page, str) or not page.startswith("https://"):
            problems.append(f"{where}: key_page must be an https URL")
        models = p.get("models")
        if not isinstance(models, list) or not models:
            problems.append(f"{where}: models must be a non-empty list")
            continue
        ids: set[str] = set()
        tag_count = {t: 0 for t in TAGS}
        for m in models:
            if not isinstance(m, dict):
                problems.append(f"{where}: model entries must be objects, not {m!r}")
                continue
            mid = m.get("id")
            if not isinstance(mid, str) or not _ID.match(mid):
                problems.append(f"{where}: model id {mid!r} is not a model name")
                continue
            if mid in ids:
                problems.append(f"{where}: model {mid} listed twice")
            ids.add(mid)
            if not isinstance(m.get("label"), str) or not m["label"].strip():
                problems.append(f"{where}: model {mid} needs a label")
            tag = m.get("tag")
            if tag is not None:
                if tag not in TAGS:
                    problems.append(f"{where}: model {mid} has the unknown tag {tag!r}")
                else:
                    tag_count[tag] += 1
        for tag in REQUIRED_TAGS:
            if tag_count[tag] != 1:
                problems.append(f"{where}: exactly one model must be tagged {tag!r} (found {tag_count[tag]})")
        for tag in TAGS:
            if tag_count[tag] > 1:
                problems.append(f"{where}: more than one model tagged {tag!r}")
        first_tag = models[0].get("tag") if isinstance(models[0], dict) else None
        if first_tag != "best":
            problems.append(f"{where}: the first model must be the 'best' pick (the wheel rests on it)")
    return problems


def check_against_models_dev(catalog: dict, models_dev: dict) -> list[str]:
    """Every model id must exist under the provider's models.dev key."""
    problems: list[str] = []
    if not isinstance(models_dev, dict):
        return [f"models.dev: expected an object of providers, got {type(models_dev).__name__}"]
    for p in catalog.get("providers", []):
        if not isinstance(p, dict):
            continue  # check() has said so
        key = p.get("models_dev") or p.get("id")
        prov = models_dev.get(key)
        if not isinstance(prov, dict):
            problems.append(f"provider {p.get('id')}: models.dev has no provider {key!r}")
            continue
        known = prov.get("models") or {}
        for m in p.get("models", []):
            if not isinstance(m, dict):
                continue
            if m.get("id") not in known:
                problems.append(f"provider {p.get('id')}: models.dev/{key} does not list {m.get('id')!r}")
    return problems


def fetch_models_dev(url: str = MODELS_DEV_URL, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310 (a fixed https URL)
        return json.loads(resp.read().decode("utf-8"))


def sync(src: Path = CATALOG, dst: Path = ANDROID_ASSET) -> Path:
    """Copy the catalog into the app's assets, byte for byte (the tests pin the two equal)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dst)
    return dst


def picks(catalog: dict) -> dict[str, str]:
    """`{provider kind: best model id}`, what each wheel rests on."""
    out: dict[str, str] = {}
    for p in catalog.get("providers", []):
        best = next((m["id"] for m in p.get("models", []) if m.get("tag") == "best"), None)
        if best:
            out[p["id"]] = best
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="validate the catalog's shape (and its ids, with --online or --models-dev)")
    c.add_argument("--catalog", type=Path, default=CATALOG)
    c.add_argument("--models-dev", type=Path, help="a saved copy of https://models.dev/api.json")
    c.add_argument("--online", action="store_true", help="fetch models.dev and check every model id")
    s = sub.add_parser("sync", help="copy the catalog into the Android app's assets")
    s.add_argument("--catalog", type=Path, default=CATALOG)
    s.add_argument("--to", type=Path, default=ANDROID_ASSET)
    p = sub.add_parser("picks", help="print the best pick per provider")
    p.add_argument("--catalog", type=Path, default=CATALOG)
    args = ap.parse_args(argv)

    catalog = load(args.catalog)
    if args.cmd == "sync":
        print(f"copied {args.catalog} -> {sync(args.catalog, args.to)}")
        return 0
    if args.cmd == "picks":
        for kind, model in picks(catalog).items():
            print(f"{kind}\t{model}")
        return 0
    problems = check(catalog)
    models_dev = None
    if args.models_dev:
        try:
            models_dev = json.loads(args.models_dev.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            problems.append(f"could not read {args.models_dev}: {e}")
    elif args.online:
        try:
            models_dev = fetch_models_dev()
        except (OSError, ValueError) as e:  # the network, or a body that is not JSON
            problems.append(f"could not fetch {MODELS_DEV_URL}: {e}")
    if models_dev is not None:
        problems += check_against_models_dev(catalog, models_dev)
    for line in problems:
        print(line, file=sys.stderr)
    if not problems:
        n = sum(len(p["models"]) for p in catalog["providers"])
        checked = " and models.dev" if models_dev is not None else ""
        print(f"ok: {len(catalog['providers'])} providers, {n} models, shape{checked} checked (updated {catalog['updated']})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
