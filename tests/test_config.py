import json
from pathlib import Path
import pytest
from niba.agent import config


CONFIG_TOML = """
[telegram]
bot_token = "tg-secret"
owner_chat_id = 42

[openrouter]
api_key = "or-secret"

[limits]
model_calls_per_hour = 90
monthly_token_budget = 1600000000
"""


def test_load_config(tmp_path):
    (tmp_path / "config.toml").write_text(CONFIG_TOML)
    cfg = config.load_config(tmp_path)
    assert cfg.telegram_token == "tg-secret"
    assert cfg.owner_chat_id == 42
    assert cfg.openrouter_api_key == "or-secret"
    assert cfg.model_calls_per_hour == 90
    assert cfg.niba_home == tmp_path


def test_load_mmx_token_roundtrip(tmp_path):
    p = tmp_path / "mmx.json"
    p.write_text(json.dumps({"access_token": "a", "refresh_token": "r", "other": 1}))
    tok = config.load_mmx_token(p)
    assert (tok.access_token, tok.refresh_token) == ("a", "r")
    tok.access_token = "a2"
    config.save_mmx_token(p, tok)
    reloaded = json.loads(p.read_text())
    assert reloaded["access_token"] == "a2"
    assert reloaded["other"] == 1  # untouched


def test_secret_values_excludes_empty(tmp_path):
    (tmp_path / "config.toml").write_text(CONFIG_TOML)
    cfg = config.load_config(tmp_path)
    vals = config.secret_values(cfg, config.MmxToken("acc", ""))
    assert "tg-secret" in vals and "or-secret" in vals and "acc" in vals
    assert "" not in vals


def test_load_mmx_token_nested_oauth(tmp_path):
    """The real mmx auth login writes a nested {"oauth": {...}} structure."""
    p = tmp_path / "mmx.json"
    p.write_text(json.dumps({
        "region": "global",
        "oauth": {"access_token": "oat-x", "refresh_token": "dfrt-y",
                  "resource_url": "https://api.minimax.io", "expires_at": "2026-09-01T01:05:07Z"},
    }))
    tok = config.load_mmx_token(p)
    assert (tok.access_token, tok.refresh_token, tok.resource_url) == (
        "oat-x", "dfrt-y", "https://api.minimax.io")
    tok.access_token = "oat-new"
    config.save_mmx_token(p, tok)
    reloaded = json.loads(p.read_text())
    assert reloaded["oauth"]["access_token"] == "oat-new"
    assert reloaded["oauth"]["expires_at"] == "2026-09-01T01:05:07Z"  # untouched
    assert reloaded["region"] == "global"
