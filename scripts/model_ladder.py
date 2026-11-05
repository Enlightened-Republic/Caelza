"""The free local model ladder (vision doc §3.4): which DeepSeek R1 build a
device gets, by where the Runtime runs and how much RAM it has.

Two tiers come out of a pick: the **agent** model (what the owner's agent
runs on when no provider key is configured) and the **guide** model (Cael,
always the 1.5B, always present). `scripts/model-setup.sh` calls this and
acts on the JSON; `bundle/manifest.toml` mirrors the names.

    python scripts/model_ladder.py --detect            # this machine, as JSON
    python scripts/model_ladder.py --ram-mb 7600 --platform termux
    python scripts/model_ladder.py --shell            # KEY=value lines for sh
    python scripts/model_ladder.py --check-online     # the pins against Hugging Face's headers

Honest sizing, not optimistic: a 7B Q4 on an 8 GB phone is tight and the
1.5B is for chat and explanation only; both are said so in `notes`.

The pins are a sha256 and a byte count per GGUF. The Termux installer
(`model-setup.sh`) checks the hash alone; the Android app checks both, so a
byte count that is off by one makes the app download a gigabyte, throw it
away and try again. `--check-online` asks Hugging Face for each file's
`x-linked-size` and `x-linked-etag` (the LFS oid, i.e. the sha256) and
compares; run it whenever a pin changes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

HF = "https://huggingface.co"

#: llama.cpp builds (phones). bartowski's GGUF conversions of the official
#: DeepSeek-R1-Distill-Qwen weights, MIT. sha256 is the Hugging Face LFS oid
#: and bytes the LFS size, both read from the files' resolve headers
#: (`--check-online`) on 2026-11-05.
GGUF = {
    "1.5b": {
        "name": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M",
        "file": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "sha256": "1741e5b2d062b07acf048bf0d2c514dadf2a48f94e2b4aa0cfe069af3838ee2f",
        "bytes": 1_117_320_800,
    },
    "7b": {
        "name": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M",
        "file": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "sha256": "731ece8d06dc7eda6f6572997feb9ee1258db0784827e642909d9b565641937b",
        "bytes": 4_683_073_504,
    },
}

#: Ollama tags (hubs). The library's deepseek-r1 distills.
OLLAMA = {
    "1.5b": "deepseek-r1:1.5b",
    "7b": "deepseek-r1:7b",
    "8b": "deepseek-r1:8b",
    "14b": "deepseek-r1:14b",
}

GUIDE_TIER = "1.5b"


@dataclass(frozen=True)
class Model:
    tier: str
    runner: str            # "llamacpp" | "ollama"
    name: str              # the Runtime's `model = …` value
    file: str = ""         # GGUF file name (llamacpp)
    url: str = ""          # download URL (llamacpp)
    sha256: str = ""       # expected digest (llamacpp)
    bytes: int = 0         # expected size (llamacpp)
    pull: str = ""         # `ollama pull` tag (ollama)


@dataclass(frozen=True)
class Pick:
    platform: str          # "termux" | "linux"
    ram_mb: int
    runner: str
    agent: Model
    guide: Model
    provider_alias_agent: str   # e.g. "llamacpp.local"
    provider_alias_guide: str   # e.g. "llamacpp.guide"
    notes: list[str]


def gguf(tier: str) -> Model:
    g = GGUF[tier]
    return Model(tier=tier, runner="llamacpp", name=g["name"], file=g["file"],
                 url=f"{HF}/{g['repo']}/resolve/main/{g['file']}",
                 sha256=g["sha256"], bytes=g["bytes"])


def ollama(tier: str) -> Model:
    return Model(tier=tier, runner="ollama", name=OLLAMA[tier], pull=OLLAMA[tier])


def pick(ram_mb: int, platform: str) -> Pick:
    """The ladder. `platform` is "termux" (a phone: llama.cpp from the Termux
    package) or "linux" (a hub, laptop or VPS: Ollama)."""
    if platform not in ("termux", "linux"):
        raise ValueError(f"platform must be termux or linux, not {platform!r}")
    notes: list[str] = []
    if platform == "termux":
        runner = "llamacpp"
        guide = gguf(GUIDE_TIER)
        if ram_mb >= 6 * 1024:
            agent = gguf("7b")
            notes.append("7B Q4 on a phone is tight: keep context short (the server runs with -c 4096)")
        else:
            agent = gguf(GUIDE_TIER)
            notes.append("<= 5 GB RAM: the 1.5B is for chat and explanation; not reliable for "
                         "multi-step tool calls. Bring a provider key for the agent loop")
        if agent.tier != guide.tier:
            notes.append("one llama-server at a time: the agent model is served on :8080; "
                         "Cael shares it unless you run a second server for the guide")
    else:
        runner = "ollama"
        guide = ollama(GUIDE_TIER)
        if ram_mb >= 16 * 1024:
            agent = ollama("14b")
        elif ram_mb >= 8 * 1024:
            agent = ollama("8b")
            notes.append("8-12 GB: 8b. 14b needs 16 GB")
        else:
            agent = ollama("7b") if ram_mb >= 6 * 1024 else ollama(GUIDE_TIER)
            notes.append("under 8 GB on a hub: expect slow turns; a provider key is the better agent brain")
    return Pick(platform=platform, ram_mb=ram_mb, runner=runner, agent=agent, guide=guide,
                provider_alias_agent=f"{runner}.local",
                provider_alias_guide=f"{runner}.guide",
                notes=notes)


def detect_platform() -> str:
    prefix = os.environ.get("PREFIX", "")
    return "termux" if "/com.termux/" in prefix else "linux"


def detect_ram_mb() -> int:
    try:
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        pass
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") // (1024 * 1024)
    except (ValueError, OSError, AttributeError):
        return 0


def as_shell(p: Pick) -> str:
    """KEY=value lines a POSIX sh can `eval`."""
    rows = {
        "PLATFORM": p.platform, "RAM_MB": p.ram_mb, "RUNNER": p.runner,
        "AGENT_TIER": p.agent.tier, "AGENT_NAME": p.agent.name, "AGENT_FILE": p.agent.file,
        "AGENT_URL": p.agent.url, "AGENT_SHA256": p.agent.sha256, "AGENT_BYTES": p.agent.bytes,
        "AGENT_PULL": p.agent.pull,
        "GUIDE_TIER": p.guide.tier, "GUIDE_NAME": p.guide.name, "GUIDE_FILE": p.guide.file,
        "GUIDE_URL": p.guide.url, "GUIDE_SHA256": p.guide.sha256, "GUIDE_BYTES": p.guide.bytes,
        "GUIDE_PULL": p.guide.pull,
        "PROVIDER_AGENT": p.provider_alias_agent, "PROVIDER_GUIDE": p.provider_alias_guide,
        "NOTES": " | ".join(p.notes),
    }
    return "\n".join(f"{k}='{str(v).replace(chr(39), chr(39) + chr(92) + chr(39) + chr(39))}'"
                     for k, v in rows.items())


def check_pins(headers: dict[str, dict[str, str]]) -> list[str]:
    """Compare the pins with what Hugging Face says about each file: `headers`
    maps a tier to the resolve endpoint's response headers (lowercase names),
    where `x-linked-size` is the LFS size and `x-linked-etag` the quoted LFS
    oid. One problem line each; empty when every pin is right."""
    problems: list[str] = []
    for tier, g in GGUF.items():
        h = headers.get(tier)
        if h is None:
            problems.append(f"{tier}: no answer from Hugging Face")
            continue
        size = h.get("x-linked-size")
        etag = (h.get("x-linked-etag") or "").strip('"')
        if size is None or etag == "":
            problems.append(f"{tier}: the resolve headers carry no x-linked-size / x-linked-etag "
                            f"(not an LFS file at {g['repo']}/{g['file']}?)")
            continue
        if int(size) != g["bytes"]:
            problems.append(f"{tier}: bytes pinned {g['bytes']}, Hugging Face says {size} "
                            f"(off by {int(size) - g['bytes']:+d})")
        if etag != g["sha256"]:
            problems.append(f"{tier}: sha256 pinned {g['sha256'][:12]}…, Hugging Face says {etag[:12]}…")
    return problems


def _head_without_redirect(url: str, timeout: float = 30.0) -> dict[str, str]:
    """The resolve endpoint's own headers: a 302 to the CDN that already names the LFS size and oid."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
            return None

    opener = urllib.request.build_opener(NoRedirect)
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "caelza model ladder"})
    try:
        with opener.open(req, timeout=timeout) as resp:
            return {k.lower(): v for k, v in resp.headers.items()}
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return {k.lower(): v for k, v in e.headers.items()}
        raise


def fetch_headers(timeout: float = 30.0) -> dict[str, dict[str, str]]:
    return {tier: _head_without_redirect(gguf(tier).url, timeout) for tier in GGUF}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="model_ladder", description=__doc__.split("\n\n")[0])
    ap.add_argument("--ram-mb", type=int, default=None, help="override detected RAM")
    ap.add_argument("--platform", choices=("termux", "linux"), default=None,
                    help="override detected platform")
    ap.add_argument("--detect", action="store_true", help="(default) detect this machine")
    ap.add_argument("--shell", action="store_true", help="print KEY=value lines instead of JSON")
    ap.add_argument("--check-online", action="store_true",
                    help="compare every GGUF pin (bytes, sha256) with Hugging Face's headers; exit 1 on a mismatch")
    a = ap.parse_args(argv)
    if a.check_online:
        try:
            headers = fetch_headers()
        except (OSError, ValueError) as e:
            print(f"could not reach Hugging Face: {e}", file=sys.stderr)
            return 1
        problems = check_pins(headers)
        for line in problems:
            print(line, file=sys.stderr)
        if not problems:
            print(f"ok: {len(GGUF)} GGUF pins match Hugging Face (bytes and sha256)")
        return 1 if problems else 0
    ram = a.ram_mb if a.ram_mb is not None else detect_ram_mb()
    platform = a.platform or detect_platform()
    p = pick(ram, platform)
    print(as_shell(p) if a.shell else json.dumps(asdict(p), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
