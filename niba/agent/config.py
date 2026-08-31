from __future__ import annotations

import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    telegram_token: str
    owner_chat_id: int
    openrouter_api_key: str
    model_calls_per_hour: int
    monthly_token_budget: int
    niba_home: Path
    repo_root: Path
    mmx_config_path: Path
    # Model HTTP retry/timeout knobs. Defaults are conservative for cellular:
    # 180s per call, up to 3 attempts total, 1s base exponential backoff
    # (1s + 2s = 3s of wait between attempts). Tunable per-deployment via
    # the [model] section of ~/.niba/config.toml.
    model_timeout_seconds: int = 180
    model_max_attempts: int = 3
    model_retry_base_seconds: float = 1.0
    firecrawl_api_key: str = ""
    tavily_api_key: str = ""
    searchapi_api_key: str = ""


@dataclass
class MmxToken:
    access_token: str
    refresh_token: str
    resource_url: str = ""


def _home(niba_home: Path | None) -> Path:
    if niba_home is not None:
        return Path(niba_home)
    return Path(os.environ.get("NIBA_HOME", Path.home() / ".niba"))


def load_config(niba_home: Path | None = None) -> Config:
    home = _home(niba_home)
    data = tomllib.loads((home / "config.toml").read_text())
    tg = data["telegram"]
    limits = data.get("limits", {})
    model = data.get("model", {})
    mmx_path = Path(
        data.get("minimax", {}).get("mmx_config_path", "~/.mmx/config.json")
    ).expanduser()
    return Config(
        telegram_token=tg["bot_token"],
        owner_chat_id=int(tg["owner_chat_id"]),
        openrouter_api_key=data.get("openrouter", {}).get("api_key", ""),
        model_calls_per_hour=int(limits.get("model_calls_per_hour", 120)),
        monthly_token_budget=int(limits.get("monthly_token_budget", 1_600_000_000)),
        niba_home=home,
        repo_root=Path(__file__).resolve().parents[2],
        mmx_config_path=mmx_path,
        model_timeout_seconds=int(model.get("timeout_seconds", 180)),
        model_max_attempts=int(model.get("max_attempts", 3)),
        model_retry_base_seconds=float(model.get("retry_base_seconds", 1.0)),
        firecrawl_api_key=data.get("firecrawl", {}).get("api_key", ""),
        tavily_api_key=data.get("tavily", {}).get("api_key", ""),
        searchapi_api_key=data.get("searchapi", {}).get("api_key", ""),
    )


def load_mmx_token(path: Path) -> MmxToken:
    """Read the token from an mmx config.json.

    The real `mmx auth login` writes ``{"region": ..., "oauth": {"access_token",
    "refresh_token", "resource_url", ...}}``. Older/flat files with top-level
    ``access_token`` are also accepted.
    """
    data = json.loads(Path(path).read_text())
    src = data.get("oauth") if isinstance(data.get("oauth"), dict) else data
    return MmxToken(
        src.get("access_token", ""),
        src.get("refresh_token", ""),
        src.get("resource_url", ""),
    )


def save_mmx_token(path: Path, token: MmxToken) -> None:
    path = Path(path)
    data = json.loads(path.read_text()) if path.exists() else {}
    dst = data["oauth"] if isinstance(data.get("oauth"), dict) else data
    dst["access_token"] = token.access_token
    dst["refresh_token"] = token.refresh_token
    if token.resource_url:
        dst["resource_url"] = token.resource_url
    path.write_text(json.dumps(data, indent=2))


def secret_values(cfg: Config, token: MmxToken | None) -> list[str]:
    vals = [cfg.telegram_token, cfg.openrouter_api_key, cfg.firecrawl_api_key,
            cfg.tavily_api_key, cfg.searchapi_api_key]
    if token:
        vals += [token.access_token, token.refresh_token]
    return [v for v in vals if v]
