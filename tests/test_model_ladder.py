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


def _headers_for(tier: str, bytes_: int | None = None, sha: str | None = None) -> dict[str, str]:
    g = ml.GGUF[tier]
    return {"x-linked-size": str(bytes_ if bytes_ is not None else g["bytes"]),
            "x-linked-etag": '"' + (sha if sha is not None else g["sha256"]) + '"'}


def test_the_pins_are_checked_against_hugging_faces_headers():
    # Right pins: nothing to say.
    assert ml.check_pins({t: _headers_for(t) for t in ml.GGUF}) == []
    # The 1.5B pinned 64 bytes short (the app's first phone run: five downloads of a gigabyte, then "short download").
    off = ml.check_pins({"1.5b": _headers_for("1.5b", bytes_=ml.GGUF["1.5b"]["bytes"] + 64), "7b": _headers_for("7b")})
    assert off == [f"1.5b: bytes pinned {ml.GGUF['1.5b']['bytes']}, Hugging Face says {ml.GGUF['1.5b']['bytes'] + 64} (off by +64)"]
    # A wrong hash, a file that is not LFS, a tier that did not answer.
    assert ml.check_pins({"1.5b": _headers_for("1.5b", sha="ab" * 32), "7b": _headers_for("7b")})[0].startswith("1.5b: sha256 pinned 1741e5b2d062…, Hugging Face says abababababab…")
    assert "not an LFS file" in ml.check_pins({"1.5b": {"content-length": "1152"}, "7b": _headers_for("7b")})[0]
    assert ml.check_pins({"7b": _headers_for("7b")}) == ["1.5b: no answer from Hugging Face"]
    # The sizes agree with the hashes' source: the Kotlin ladder and the app's fixture carry the same numbers.
    kt = (REPO_ROOT / "android/app/src/main/java/tech/enlightenedrepublic/caelza/model/ModelLadder.kt").read_text()
    fixture = json.loads((REPO_ROOT / "android/app/src/test/fixtures/model-ladder.json").read_text())
    for tier, g in ml.GGUF.items():
        assert f"{g['bytes']:_}L" in kt, (tier, g["bytes"])
        assert fixture["gguf"][tier]["bytes"] == g["bytes"]


@pytest.mark.skipif(not __import__("os").environ.get("CAELZA_ONLINE_TESTS"), reason="CAELZA_ONLINE_TESTS=1 asks Hugging Face")
def test_the_pins_match_hugging_face_right_now(capsys):
    assert ml.main(["--check-online"]) == 0
    assert "ok: 2 GGUF pins match Hugging Face" in capsys.readouterr().out


def test_cli_json_and_detection(capsys):
    assert ml.main(["--ram-mb", "16384", "--platform", "linux"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["agent"]["pull"] == "deepseek-r1:14b" and out["guide"]["tier"] == "1.5b"
    assert ml.detect_ram_mb() > 0
    assert ml.detect_platform() in ("termux", "linux")
