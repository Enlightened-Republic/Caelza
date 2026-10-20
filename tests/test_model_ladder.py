"""The free-local-model ladder: honest sizes, stable names, shell-safe output."""
from __future__ import annotations

import json
import re
import shlex
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import model_ladder as ml  # noqa: E402


@pytest.mark.parametrize("ram_mb, tier", [
    (3_500, "1.5b"), (5_000, "1.5b"), (6 * 1024, "7b"), (7_600, "7b"), (12 * 1024, "7b"),
])
def test_phone_ladder(ram_mb, tier):
    p = ml.pick(ram_mb, "termux")
    assert p.runner == "llamacpp"
    assert p.agent.tier == tier and p.agent.runner == "llamacpp"
    assert p.guide.tier == "1.5b" and p.guide.file.endswith(".gguf")
    assert p.provider_alias_agent == "llamacpp.local" and p.provider_alias_guide == "llamacpp.guide"
    assert p.agent.url.startswith("https://huggingface.co/") and p.agent.url.endswith(p.agent.file)
    assert re.fullmatch(r"[0-9a-f]{64}", p.agent.sha256)


@pytest.mark.parametrize("ram_mb, tag", [
    (4 * 1024, "deepseek-r1:1.5b"), (6 * 1024, "deepseek-r1:7b"), (8 * 1024, "deepseek-r1:8b"),
    (12 * 1024, "deepseek-r1:8b"), (16 * 1024, "deepseek-r1:14b"), (64 * 1024, "deepseek-r1:14b"),
])
def test_hub_ladder(ram_mb, tag):
    p = ml.pick(ram_mb, "linux")
    assert p.runner == "ollama"
    assert p.agent.name == p.agent.pull == tag
    assert p.guide.pull == "deepseek-r1:1.5b"
    assert p.provider_alias_agent == "ollama.local"


def test_small_phone_is_told_the_truth():
    p = ml.pick(4_000, "termux")
    assert any("not reliable for" in n for n in p.notes)
    assert p.agent == p.guide  # one model, one server


def test_unknown_platform_rejected():
    with pytest.raises(ValueError):
        ml.pick(8_000, "windows")


def test_manifest_names_match_the_ladder():
    m = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text())["defaults"]["model"]
    assert m["guide"] == ml.OLLAMA["1.5b"]
    assert m["hub"] == ml.OLLAMA["14b"]
    assert m["phone_8gb"] == ml.GGUF["7b"]["name"]
    assert m["phone_5gb"] == ml.GGUF["1.5b"]["name"]
    assert m["guide_gguf_sha256"] == ml.GGUF["1.5b"]["sha256"]


def test_shell_output_is_evaluable_by_sh(tmp_path):
    p = ml.pick(7_600, "termux")
    text = ml.as_shell(p)
    script = tmp_path / "t.sh"
    script.write_text(text + '\nprintf "%s|%s|%s\\n" "$RUNNER" "$AGENT_NAME" "$GUIDE_FILE"\n')
    out = subprocess.run(["sh", str(script)], capture_output=True, text=True, check=True).stdout
    assert out.strip() == f"llamacpp|{p.agent.name}|{p.guide.file}"
    for line in text.splitlines():  # every value is one single-quoted token
        key, _, value = line.partition("=")
        assert key.isupper() and shlex.split(value) == [shlex.split(value)[0]]


def test_cli_json_and_detection(capsys):
    assert ml.main(["--ram-mb", "16384", "--platform", "linux"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["agent"]["pull"] == "deepseek-r1:14b" and out["guide"]["tier"] == "1.5b"
    assert ml.detect_ram_mb() > 0
    assert ml.detect_platform() in ("termux", "linux")
