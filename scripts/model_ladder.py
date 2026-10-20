"""The free local model ladder (vision doc §3.4): which DeepSeek R1 build a
device gets, by where the Runtime runs and how much RAM it has.

Two tiers come out of a pick: the **agent** model (what the owner's agent
runs on when no provider key is configured) and the **guide** model (Cael,
always the 1.5B, always present). `scripts/model-setup.sh` calls this and
acts on the JSON; `bundle/manifest.toml` mirrors the names.

    python scripts/model_ladder.py --detect            # this machine, as JSON
    python scripts/model_ladder.py --ram-mb 7600 --platform termux
    python scripts/model_ladder.py --shell            # KEY=value lines for sh

Honest sizing, not optimistic: a 7B Q4 on an 8 GB phone is tight and the
1.5B is for chat and explanation only; both are said so in `notes`.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass

HF = "https://huggingface.co"

#: llama.cpp builds (phones). bartowski's GGUF conversions of the official
#: DeepSeek-R1-Distill-Qwen weights, MIT. sha256 is the Hugging Face LFS oid,
#: read from the repo tree on 2026-10-20.
GGUF = {
    "1.5b": {
        "name": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M",
        "file": "DeepSeek-R1-Distill-Qwen-1.5B-Q4_K_M.gguf",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-1.5B-GGUF",
        "sha256": "1741e5b2d062b07acf048bf0d2c514dadf2a48f94e2b4aa0cfe069af3838ee2f",
        "bytes": 1_117_320_736,
    },
    "7b": {
        "name": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M",
        "file": "DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf",
        "repo": "bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF",
        "sha256": "731ece8d06dc7eda6f6572997feb9ee1258db0784827e642909d9b565641937b",
        "bytes": 4_683_073_184,
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="model_ladder", description=__doc__.split("\n\n")[0])
    ap.add_argument("--ram-mb", type=int, default=None, help="override detected RAM")
    ap.add_argument("--platform", choices=("termux", "linux"), default=None,
                    help="override detected platform")
    ap.add_argument("--detect", action="store_true", help="(default) detect this machine")
    ap.add_argument("--shell", action="store_true", help="print KEY=value lines instead of JSON")
    a = ap.parse_args(argv)
    ram = a.ram_mb if a.ram_mb is not None else detect_ram_mb()
    platform = a.platform or detect_platform()
    p = pick(ram, platform)
    print(as_shell(p) if a.shell else json.dumps(asdict(p), indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
