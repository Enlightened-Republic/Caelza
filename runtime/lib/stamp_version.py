#!/usr/bin/env python3
"""Stamp a release's version into the staged Runtime workspace.

    stamp_version.py <staged-runtime-tree> <build-id> <upstream-version>

The staged tree carries upstream's crate version (0.8.6 at the current pin) and
the binary reports it: `caelza --version` answers `<crate version> (<build id>)`.
A Caelza release is named by its tag (v0.1.0 → caelza-0.1.0-<target>.tar.gz),
and both installers (`caelza_body/runtime_guard.py`, the app's ReleaseInstaller)
probe the binary's version against the release's before trusting it, so a
release build has to carry the tag's version. Before cargo runs, this rewrites

  - `[workspace.package] version` in Cargo.toml (every member inherits it),
  - the `version` requirement of every path dependency under
    `[workspace.dependencies]` (a requirement of 0.8.6 would not accept 0.1.0),
  - the entry of every workspace member in Cargo.lock, so `--locked` still
    passes. Registry packages that share the number (rand 0.8.6) are left alone.

The version is the one the build id names: `v0.1.0`, `v0.1.0+zeroclaw.c4732213`,
`v0.1.0-rc1`. A build id that names none (`main`, `dev-abcdef12+…`) or names
upstream's own version (the dev default, `v0.8.6+zeroclaw.…`) leaves the tree as
upstream has it. Nothing here needs cargo or the network; `cargo build --locked`
is the final check that the lock still matches.
"""
from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

# v<semver> with an optional +<build metadata>: the tag the release workflow
# builds, with the upstream commit appended.
BUILD_ID = re.compile(r"^v(\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?)(?:\+[0-9A-Za-z.-]+)?$")

# A Cargo.lock entry: name, version, then `source` for a registry package or
# straight on to `dependencies` / the next entry for a path package.
LOCK_ENTRY = re.compile(r'(\[\[package\]\]\nname = "(?P<name>[^"]+)"\nversion = ")(?P<version>[^"]+)("\n)(?!source)')

SKIP_DIRS = frozenset({".git", "target", "node_modules", "vendor"})


class StampError(Exception):
    pass


def version_from_build_id(build_id: str) -> str | None:
    """`v0.1.0+zeroclaw.c4732213` → `0.1.0`; None when the id names no release version."""
    m = BUILD_ID.match(build_id.strip())
    return m.group(1) if m else None


def workspace_members(tree: Path) -> set[str]:
    """Names of the packages whose version is the workspace's (`version.workspace = true`)."""
    names = set()
    for manifest in sorted(tree.rglob("Cargo.toml")):
        if SKIP_DIRS & set(manifest.relative_to(tree).parts):
            continue
        pkg = tomllib.loads(manifest.read_text(encoding="utf-8")).get("package") or {}
        if pkg.get("version") == {"workspace": True} and pkg.get("name"):
            names.add(pkg["name"])
    return names


def stamp_manifest(text: str, upstream: str, version: str) -> tuple[str, int, int]:
    """Cargo.toml: the workspace version and the path dependencies' requirements."""
    up = re.escape(upstream)
    out, section, packages, requirements = [], None, 0, 0
    for line in text.splitlines(keepends=True):
        head = re.match(r"^\[([^\]]+)\]", line)
        if head:
            section = head.group(1)
        elif section == "workspace.package" and re.match(rf'^version\s*=\s*"{up}"', line):
            line = re.sub(rf'^(version\s*=\s*"){up}"', rf'\g<1>{version}"', line)
            packages += 1
        elif section == "workspace.dependencies" and re.search(r"\bpath\s*=", line) \
                and re.search(rf'\bversion\s*=\s*"{up}"', line):
            line = re.sub(rf'(\bversion\s*=\s*"){up}"', rf'\g<1>{version}"', line)
            requirements += 1
        out.append(line)
    return "".join(out), packages, requirements


def stamp_lock(text: str, upstream: str, version: str) -> tuple[str, set[str]]:
    """Cargo.lock: every path package at the upstream version; registry packages untouched."""
    names: set[str] = set()

    def swap(m: re.Match) -> str:
        if m.group("version") != upstream:
            return m.group(0)
        names.add(m.group("name"))
        return f"{m.group(1)}{version}{m.group(4)}"

    return LOCK_ENTRY.sub(swap, text), names


def stamp(tree: Path, version: str, upstream: str) -> dict:
    """Rewrite the tree in place; the counts of what changed. Raises StampError when
    the tree does not look like upstream's workspace at `upstream`."""
    manifest, lock = tree / "Cargo.toml", tree / "Cargo.lock"
    for f in (manifest, lock):
        if not f.is_file():
            raise StampError(f"{f} is missing: not a staged workspace")
    new_manifest, packages, requirements = stamp_manifest(manifest.read_text(encoding="utf-8"), upstream, version)
    if packages != 1:
        raise StampError(f"{manifest}: expected one [workspace.package] version = \"{upstream}\", found {packages}")
    new_lock, names = stamp_lock(lock.read_text(encoding="utf-8"), upstream, version)
    members = workspace_members(tree)
    if names != members:
        raise StampError(
            f"{lock}: the entries at {upstream} are not the workspace members "
            f"(in the lock only: {sorted(names - members) or '-'}; members not in the lock: {sorted(members - names) or '-'})")
    # Read back what cargo will read.
    parsed = tomllib.loads(new_manifest)
    if parsed["workspace"]["package"]["version"] != version:
        raise StampError(f"{manifest}: the workspace version did not take")
    stale = sorted(n for n, d in parsed["workspace"].get("dependencies", {}).items()
                   if isinstance(d, dict) and "path" in d and d.get("version") not in (None, version))
    if stale:
        raise StampError(f"{manifest}: path dependencies still require another version: {stale}")
    manifest.write_text(new_manifest, encoding="utf-8")
    lock.write_text(new_lock, encoding="utf-8")
    return {"version": version, "upstream": upstream, "package": packages,
            "requirements": requirements, "lock": len(names)}


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    tree, build_id, upstream = Path(argv[0]), argv[1], argv[2]
    version = version_from_build_id(build_id)
    try:
        if version is None:
            print(f"crates stay at upstream's {upstream}: build id {build_id} names no release version")
        elif version == upstream:
            print(f"crates stay at upstream's {upstream}: build id {build_id} names the same version")
        else:
            done = stamp(tree, version, upstream)
            print(f"version {version} stamped over upstream's {upstream}: Cargo.toml (the workspace version, "
                  f"{done['requirements']} path requirements), Cargo.lock ({done['lock']} members)")
    except (StampError, OSError, tomllib.TOMLDecodeError, KeyError) as e:
        print(f"stamp_version: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
