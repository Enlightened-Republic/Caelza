from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

import httpx

from niba.agent import config as _config

_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

#: Transport-level errors worth retrying. These are the ones a flaky cellular
#: link can cause: connection drops, mid-stream read timeouts, remote-side
#: protocol resets. We do NOT retry on HTTP 4xx/5xx — those are server responses
#: that the caller has to inspect (401 still goes through the explicit refresh
#: path in `complete`; 429 means the quota is genuinely exhausted).
_RETRYABLE_TRANSPORT: tuple[type[httpx.HTTPError], ...] = (
    httpx.TimeoutException,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
    httpx.ReadError,
)


def _visible(content: str | None) -> str | None:
    """Strip MiniMax M3's <think>...</think> reasoning from user-facing text.

    The raw message (with <think>) still goes back to the model as history —
    only what the owner sees / what's logged as the assistant turn is cleaned.
    """
    if not content:
        return content
    return _THINK_RE.sub("", content).strip() or None


class ModelPaused(RuntimeError): ...
class ModelAuthError(RuntimeError): ...
class ModelQuotaExhausted(RuntimeError): ...


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Assistant:
    content: str | None
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


class Model:
    DEFAULT_BASE_URL = "https://api.minimax.io/v1"
    MODEL = "MiniMax-M3"

    def __init__(self, config, session, client: httpx.Client):
        self.cfg = config
        self.session = session
        self.c = client
        self.token = _config.load_mmx_token(config.mmx_config_path)

    @property
    def base_url(self) -> str:
        # mmx's config carries the account's own API host; fall back to the default.
        ru = (self.token.resource_url or "").rstrip("/")
        return f"{ru}/v1" if ru else self.DEFAULT_BASE_URL

    def complete(self, messages, tools):
        if self.session.calls_last_hour() >= self.cfg.model_calls_per_hour:
            raise ModelPaused("hourly model-call cap reached")
        body = {"model": self.MODEL, "messages": messages}
        if tools:
            body["tools"] = tools
        resp = self._post(body)
        if resp.status_code == 401:
            self._refresh()
            resp = self._post(body)
            if resp.status_code == 401:
                raise ModelAuthError("still 401 after refresh")
        if resp.status_code == 429:
            raise ModelQuotaExhausted("HTTP 429 from the model API")
        try:
            data = resp.json()
        except ValueError:
            # Non-JSON error body (a 5xx HTML page): surface it as an
            # httpx.HTTPStatusError, which loop.run() already handles.
            resp.raise_for_status()
            raise  # 2xx with a non-JSON body — shouldn't happen, don't swallow it
        if self._is_quota_error(resp.status_code, data):
            raise ModelQuotaExhausted(str(data))
        resp.raise_for_status()
        u = data.get("usage", {})
        self.session.log_tokens(u.get("prompt_tokens", 0), u.get("completion_tokens", 0))
        msg = data["choices"][0]["message"]
        calls = [
            ToolCall(tc["id"], tc["function"]["name"], json.loads(tc["function"]["arguments"] or "{}"))
            for tc in msg.get("tool_calls", []) or []
        ]
        return Assistant(content=_visible(msg.get("content")), tool_calls=calls, raw=msg)

    def _post(self, body):
        """POST to chat/completions, retrying on transient transport failures.

        Timeouts, connection drops, and remote protocol errors are retried with
        exponential backoff. HTTP 4xx/5xx are NOT retried — they're real server
        responses, and the body matters. Auth (401) is handled in `complete` via
        an explicit refresh; quota (429) is surfaced immediately.
        """
        timeout = self.cfg.model_timeout_seconds
        base = self.cfg.model_retry_base_seconds
        max_attempts = max(1, self.cfg.model_max_attempts)
        headers = {"Authorization": f"Bearer {self.token.access_token}"}
        url = f"{self.base_url}/chat/completions"
        last_err: httpx.HTTPError | None = None
        for attempt in range(max_attempts):
            try:
                return self.c.post(url, json=body, timeout=timeout, headers=headers)
            except _RETRYABLE_TRANSPORT as e:
                last_err = e
                if attempt + 1 >= max_attempts:
                    raise
                # Exponential backoff: base * 2^attempt between attempts. With
                # defaults (3 attempts, 1s base), waits are 1s before retry 2
                # and 2s before retry 3 — bounded by base * (2^(n-1) - 1).
                time.sleep(base * (2 ** attempt))
        raise last_err  # unreachable; satisfies type checkers

    # Overridable in tests; on-device this runs the mmx CLI's own refresh.
    REFRESH_CMD = ["mmx", "auth", "refresh"]

    def _refresh(self):
        """Refresh the OAuth token by delegating to the mmx CLI, then reload it.

        MiniMax's OAuth token endpoint isn't published; `mmx auth refresh` owns
        that flow and rewrites ~/.mmx/config.json. If it isn't available or fails,
        the owner has to re-run `mmx auth login`.
        """
        import subprocess

        try:
            r = subprocess.run(self.REFRESH_CMD, capture_output=True, text=True, timeout=60)
        except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.SubprocessError) as e:
            raise ModelAuthError(f"mmx auth refresh unavailable: {e} — run `mmx auth login`")
        if r.returncode != 0:
            raise ModelAuthError(f"mmx auth refresh failed: {r.stderr.strip()[:200]}")
        self.token = _config.load_mmx_token(self.cfg.mmx_config_path)

    @staticmethod
    def _is_quota_error(status, data):
        if status == 429:
            return True
        code = str((data or {}).get("base_resp", {}).get("status_code", ""))
        return code in {"1008", "1002"}  # insufficient balance / rate — executor verifies codes
