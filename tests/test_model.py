import dataclasses
import json
import httpx
import pytest
from caelza_body.agent.config import Config, MmxToken
from caelza_body.agent.session import Session
from caelza_body.agent.model import Model, ToolCall, ModelPaused, ModelQuotaExhausted


def cfg(tmp_path, cap=100):
    (tmp_path / "mmx.json").write_text(json.dumps({"access_token": "AT", "refresh_token": "RT"}))
    return Config("tg", 1, "or", cap, 10**12, tmp_path, tmp_path, tmp_path / "mmx.json")


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://api.minimax.io")


def test_complete_returns_text(tmp_path):
    def h(req):
        assert req.headers["authorization"] == "Bearer AT"
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "hello"}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 3},
        })
    s = Session(tmp_path / "s.db")
    m = Model(cfg(tmp_path), s, client(h))
    a = m.complete([{"role": "user", "content": "hi"}], [])
    assert a.content == "hello"
    assert s.tokens_this_month() == 13


def test_complete_parses_tool_calls(tmp_path):
    def h(req):
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function",
                            "function": {"name": "shell_run", "arguments": "{\"cmd\": \"ls\"}"}}],
            "reasoning_details": [{"type": "text", "text": "thinking"}],
        }}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    m = Model(cfg(tmp_path), Session(tmp_path / "s.db"), client(h))
    a = m.complete([{"role": "user", "content": "run ls"}], [])
    assert a.tool_calls == [ToolCall("c1", "shell_run", {"cmd": "ls"})]
    assert a.raw["reasoning_details"] == [{"type": "text", "text": "thinking"}]


def test_hourly_cap_raises_before_calling(tmp_path):
    s = Session(tmp_path / "s.db")
    for _ in range(3):
        s.log_tokens(1, 1)
    m = Model(cfg(tmp_path, cap=3), s, client(lambda r: httpx.Response(500)))
    with pytest.raises(ModelPaused):
        m.complete([{"role": "user", "content": "hi"}], [])


def test_5xx_with_html_body_raises_httpstatuserror_not_jsondecodeerror(tmp_path):
    """T10: loop.run's `except httpx.HTTPError` must be able to catch this.

    A MiniMax 503 comes back as an HTML error page; `resp.json()` used to blow
    up with a JSONDecodeError, which fell through to the generic 3-strike path.
    """
    html = "<html><head><title>503 Service Unavailable</title></head></html>"
    m = Model(cfg(tmp_path), Session(tmp_path / "s.db"),
              client(lambda r: httpx.Response(503, text=html)))
    with pytest.raises(httpx.HTTPStatusError) as ei:
        m.complete([{"role": "user", "content": "hi"}], [])
    assert ei.value.response.status_code == 503


def test_429_raises_quota_exhausted_without_parsing_the_body(tmp_path):
    m = Model(cfg(tmp_path), Session(tmp_path / "s.db"),
              client(lambda r: httpx.Response(429, text="<html>rate limited</html>")))
    with pytest.raises(ModelQuotaExhausted):
        m.complete([{"role": "user", "content": "hi"}], [])


def test_quota_error_from_base_resp_code_still_detected(tmp_path):
    m = Model(cfg(tmp_path), Session(tmp_path / "s.db"),
              client(lambda r: httpx.Response(200, json={"base_resp": {"status_code": 1008}})))
    with pytest.raises(ModelQuotaExhausted):
        m.complete([{"role": "user", "content": "hi"}], [])


def test_401_triggers_refresh_then_retry(tmp_path):
    import sys
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(401, json={"error": "expired"})
        assert req.headers["authorization"] == "Bearer AT2"
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "ok"}}],
                                         "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    c = cfg(tmp_path)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    # simulate `mmx auth refresh` rewriting ~/.mmx/config.json with a new token
    rewrite = (
        "import json,pathlib;"
        f"p=pathlib.Path(r'{tmp_path / 'mmx.json'}');"
        "d=json.loads(p.read_text());d['access_token']='AT2';d['refresh_token']='RT2';"
        "p.write_text(json.dumps(d))"
    )
    m.REFRESH_CMD = [sys.executable, "-c", rewrite]
    a = m.complete([{"role": "user", "content": "hi"}], [])
    assert a.content == "ok"
    assert json.loads((tmp_path / "mmx.json").read_text())["access_token"] == "AT2"


def test_base_url_from_resource_url(tmp_path):
    c = cfg(tmp_path)  # writes a flat mmx.json; overwrite it with the real nested shape
    (tmp_path / "mmx.json").write_text(json.dumps(
        {"region": "global",
         "oauth": {"access_token": "T", "refresh_token": "R", "resource_url": "https://api.minimax.io"}}
    ))
    m = Model(c, Session(tmp_path / "s.db"), client(lambda r: httpx.Response(200, json={})))
    assert m.base_url == "https://api.minimax.io/v1"
    assert m.token.access_token == "T"


def test_strips_think_blocks_from_visible_content(tmp_path):
    raw = "<think>the owner said hi, i should greet</think>\n\nhey, what's up?"
    def h(req):
        return httpx.Response(200, json={"choices": [{"message": {
            "role": "assistant", "content": raw}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1}})
    m = Model(cfg(tmp_path), Session(tmp_path / "s.db"), client(h))
    a = m.complete([{"role": "user", "content": "hi"}], [])
    assert a.content == "hey, what's up?"
    assert "<think>" in a.raw["content"]  # history keeps the full message


# ---------------------------------------------------------------------------
# Transport-level retry: timeouts, connection drops, remote protocol errors.
# HTTP 4xx/5xx must NOT be retried (server response = inspectable fact, not
# a transient link failure). Auth (401) and quota (429) take their own paths.
# ---------------------------------------------------------------------------

def test_retries_then_succeeds_on_transient_timeout(tmp_path):
    """A TimeoutException on attempt 1 or 2 must be retried, not surfaced."""
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] < 3:
            raise httpx.ReadTimeout("transient")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
    c = dataclasses.replace(cfg(tmp_path), model_retry_base_seconds=0.0)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    a = m.complete([{"role": "user", "content": "hi"}], [])
    assert a.content == "ok"
    assert calls["n"] == 3  # 2 failures + 1 success


def test_retries_then_succeeds_on_connect_error(tmp_path):
    """A dropped connection mid-handshake is also worth retrying."""
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("no route to host")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
    c = dataclasses.replace(cfg(tmp_path), model_retry_base_seconds=0.0)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    a = m.complete([{"role": "user", "content": "hi"}], [])
    assert a.content == "ok"
    assert calls["n"] == 2


def test_gives_up_after_max_attempts_on_persistent_timeout(tmp_path):
    """If every attempt times out, the underlying error must surface."""
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        raise httpx.ReadTimeout("still down")
    c = dataclasses.replace(cfg(tmp_path), model_max_attempts=3, model_retry_base_seconds=0.0)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    with pytest.raises(httpx.ReadTimeout):
        m.complete([{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 3


def test_does_not_retry_on_5xx(tmp_path):
    """A 503 is a server response, not a transport hiccup. Retry it = bad idea."""
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        return httpx.Response(503, text="<html>down</html>")
    c = dataclasses.replace(cfg(tmp_path), model_retry_base_seconds=0.0)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    with pytest.raises(httpx.HTTPStatusError):
        m.complete([{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 1


def test_does_not_retry_on_4xx(tmp_path):
    """A 400 means we sent bad input — retrying won't help."""
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})
    c = dataclasses.replace(cfg(tmp_path), model_retry_base_seconds=0.0)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    with pytest.raises(httpx.HTTPStatusError):
        m.complete([{"role": "user", "content": "hi"}], [])
    assert calls["n"] == 1


def test_max_attempts_default_is_three(tmp_path):
    """The defaults baked into Config are the safe cellular-friendly values."""
    assert cfg(tmp_path).model_max_attempts == 3
    assert cfg(tmp_path).model_timeout_seconds == 180
    assert cfg(tmp_path).model_retry_base_seconds == 1.0


def test_retry_backoff_uses_exponential_schedule(tmp_path, monkeypatch):
    """Sleep durations between attempts must follow base * 2^attempt."""
    sleeps: list[float] = []
    monkeypatch.setattr("caelza_body.agent.model.time.sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}
    def h(req):
        calls["n"] += 1
        if calls["n"] < 4:  # fail first 3, succeed on the 4th
            raise httpx.ConnectError("flap")
        return httpx.Response(200, json={
            "choices": [{"message": {"role": "assistant", "content": "ok"}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1},
        })
    c = dataclasses.replace(cfg(tmp_path), model_max_attempts=4, model_retry_base_seconds=0.5)
    m = Model(c, Session(tmp_path / "s.db"), client(h))
    m.complete([{"role": "user", "content": "hi"}], [])
    # 4 attempts: 3 failures + 1 success. Sleeps between attempts (0->1, 1->2,
    # 2->3) follow base * 2^attempt = 0.5, 1.0, 2.0.
    assert calls["n"] == 4
    assert sleeps == [0.5, 1.0, 2.0]
