#!/usr/bin/env python3
"""A recorded phone standing in for `adb` in the playbook evals.

Answers each remote script the playbook tools send with the fixture that
matches it, so the four tools run end to end (adb wrapper, remote script,
parser) with no device. The eval installs this file on PATH as `adb`;
`CAELZA_FIXTURES` names the directory with the recordings.
"""
import os
import sys
from pathlib import Path

FIXTURES = Path(os.environ["CAELZA_FIXTURES"])
SNAPSHOT = Path(os.environ["CAELZA_SNAPSHOT"])


def packages(flag=""):
    names = [line.strip().rsplit("=", 1)[-1] for line in SNAPSHOT.read_text().splitlines() if line.strip()]
    third = {"com.govee.home", "com.tailscale.ipn", "com.termux", "com.termux.api",
             "com.example.flashlightpro", "com.cleaner.boost.master"}
    extra = ["com.example.flashlightpro", "com.cleaner.boost.master", "com.termux", "com.termux.api"]
    names = sorted(set(names) | set(extra))
    if flag == "-3":
        names = [n for n in names if n in third]
    if flag == "-d":
        names = ["com.tmobile.echolocate"]  # already disabled by hand
    return "".join(f"package:{n}\n" for n in names) + "@@caelza:end\n"


def main(argv):
    joined = " ".join(argv)
    if argv[:1] == ["connect"]:
        print(f"connected to {argv[1]}")
        return 0
    if "devices" in argv[:2]:
        print("List of devices attached\n127.0.0.1:5555\tdevice")
        return 0
    if "shell" not in argv:
        print(f"args: {joined}")
        return 0
    script = " ".join(argv[argv.index("shell") + 1:])
    if "echo '@@caelza:pkg'; dumpsys package" in script:
        out = (FIXTURES / "foreground-detail.txt").read_text()
    elif "pm list packages -i" in script:
        out = (FIXTURES / "pm-list-i.txt").read_text()
    elif "pm list packages -3" in script:
        out = packages("-3")
    elif "pm list packages -d" in script:
        out = packages("-d")
    elif script.startswith("pm list packages"):
        out = packages()
    elif "@@caelza:identity" in script:
        out = (FIXTURES / "health.txt").read_text()
    elif "mCurrentFocus" in script:
        out = (FIXTURES / "window-popup.txt").read_text()
    elif "d=$(dumpsys package" in script:
        out = (FIXTURES / "suspects.txt").read_text()
    else:
        out = f"args: {joined}\n"
    sys.stdout.write(out)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
