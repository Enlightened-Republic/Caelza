#!/usr/bin/env python3
"""The Android app's version from the release tag (release.yml's `app` job).

The Runtime carries the tag's version in its crates (runtime/lib/stamp_version.py);
the app carries it in the APK the same way, so `caelza-app-0.1.0.apk` says
0.1.0 in Settings and in the bug report. One rule, in one place:

    v0.1.0        → versionName 0.1.0,      versionCode 1000,    build id v0.1.0
    v12.3.4       → versionName 12.3.4,     versionCode 12003004
    v0.1.0-rc.1   → versionName 0.1.0-rc.1, versionCode 1000     (a pre-release shares its final's code)
    anything else → versionName dev-<sha8>, versionCode 1        (a workflow_dispatch run, a local build)

versionCode is major × 1 000 000 + minor × 1 000 + patch, so every later tag
upgrades every earlier one and a dev build (code 1) is upgraded by any tag.
Minor and patch stay below 1 000, major below 2 100, Android's 2 100 000 000.

    python3 scripts/app_version.py v0.1.0                 # a summary
    python3 scripts/app_version.py v0.1.0 --gradle        # -PcaelzaVersion=0.1.0 -PcaelzaVersionCode=1000 -PcaelzaBuildId=v0.1.0
    python3 scripts/app_version.py dev --sha $GITHUB_SHA --github >> $GITHUB_OUTPUT
"""
from __future__ import annotations

import argparse
import re
import sys

TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
MAX_CODE = 2_100_000_000
DEV_CODE = 1


class VersionError(ValueError):
    pass


def version_code(major: int, minor: int, patch: int) -> int:
    if minor >= 1000 or patch >= 1000:
        raise VersionError(f"minor and patch must stay below 1000 for the versionCode scheme: {major}.{minor}.{patch}")
    code = major * 1_000_000 + minor * 1_000 + patch
    if code > MAX_CODE:
        raise VersionError(f"versionCode {code} is past Android's {MAX_CODE}")
    return code


def app_version(ref: str, sha: str = "") -> dict:
    """`{"version", "code", "build_id", "release": bool}` for a tag; the dev build for anything else."""
    ref = (ref or "").strip()
    m = TAG.match(ref)
    if not m:
        short = (sha or "").strip()[:8] or "local"
        return {"version": f"dev-{short}", "code": DEV_CODE, "build_id": f"dev-{short}", "release": False}
    major, minor, patch, pre = int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4)
    version = f"{major}.{minor}.{patch}" + (f"-{pre}" if pre else "")
    return {"version": version, "code": version_code(major, minor, patch), "build_id": ref, "release": True}


def gradle_args(v: dict) -> str:
    return f"-PcaelzaVersion={v['version']} -PcaelzaVersionCode={v['code']} -PcaelzaBuildId={v['build_id']}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ref", help="the git ref: a v<major>.<minor>.<patch>[-pre] tag, or anything else for a dev build")
    p.add_argument("--sha", default="", help="the commit, named by a dev build's version")
    out = p.add_mutually_exclusive_group()
    out.add_argument("--gradle", action="store_true", help="the -P properties for ./gradlew, on one line")
    out.add_argument("--github", action="store_true", help="key=value lines for $GITHUB_OUTPUT (version, code, build_id, release, gradle)")
    a = p.parse_args(argv)
    try:
        v = app_version(a.ref, a.sha)
    except VersionError as e:
        print(f"app_version: {e}", file=sys.stderr)
        return 1
    if a.gradle:
        print(gradle_args(v))
    elif a.github:
        print(f"version={v['version']}")
        print(f"code={v['code']}")
        print(f"build_id={v['build_id']}")
        print(f"release={'true' if v['release'] else 'false'}")
        print(f"gradle={gradle_args(v)}")
    else:
        kind = "release" if v["release"] else "dev build"
        print(f"{kind}: versionName {v['version']}, versionCode {v['code']}, build id {v['build_id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
