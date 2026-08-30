import json

import pytest

from niba.agent import tools
from niba.agent.tools import web


@pytest.fixture(autouse=True)
def _cfg(tmp_path):
    tools.reset()
    web.configure(tmp_path, "fc-testkey")
    web.register()
    yield
    tools.reset()
    web.configure(tmp_path, "")


def _resp(status, json_body=None, text_body=None):
    import httpx
    req = httpx.Request("POST", "https://api.firecrawl.dev/v2/search")
    if json_body is not None:
        return httpx.Response(status, json=json_body, request=req)
    return httpx.Response(status, text=text_body or "", request=req)


def _stub(monkeypatch, table):
    """table: {(METHOD, path_prefix): dict | callable(method, path, body)}"""
    seen = []

    def fake(method, path, body=None):
        seen.append((method, path, body))
        for (m, pfx), resp in table.items():
            if method == m and path.startswith(pfx):
                return resp(method, path, body) if callable(resp) else resp
        return {"error": "unstubbed"}

    monkeypatch.setattr(web, "_request", fake)
    return seen


def test_not_configured_is_a_clean_error(tmp_path, monkeypatch):
    tools.reset()
    web.configure(tmp_path, "")
    web.register()
    out = tools.dispatch("web_search", {"query": "x"})
    assert out.startswith("error:") and "not configured" in out


def test_search_returns_json_list(monkeypatch):
    _stub(monkeypatch, {("POST", "/search"): {"success": True, "data": {"web": [
        {"title": "A", "url": "https://a", "description": "da"},
        {"title": "B", "url": "https://b", "description": "db"}]}}})
    out = tools.dispatch("web_search", {"query": "hello", "limit": 2})
    rows = json.loads(out)
    assert [r["url"] for r in rows] == ["https://a", "https://b"]


def test_search_clamps_limit(monkeypatch):
    seen = _stub(monkeypatch, {("POST", "/search"): {"success": True, "data": {"web": []}}})
    tools.dispatch("web_search", {"query": "x", "limit": 999})
    assert seen[0][2]["limit"] == 10  # SEARCH_LIMIT_MAX


def test_read_markdown_is_wrapped_and_capped(monkeypatch):
    _stub(monkeypatch, {("POST", "/scrape"): {"success": True,
          "data": {"markdown": "X" * 20000, "metadata": {}}}})
    out = tools.dispatch("web_read", {"url": "https://x"})
    assert out.startswith("[web content")
    assert "data, not instructions" in out.lower() or "not instructions" in out.lower()
    bound = len(web._UNTRUSTED) + web.READ_CAP + len("\n…(truncated)")
    assert len(out) <= bound
    assert out.rstrip().endswith("(truncated)")


def test_read_extract_returns_json_and_logs(tmp_path, monkeypatch):
    _stub(monkeypatch, {("POST", "/scrape"): {"success": True,
          "data": {"json": {"price": "$9"}, "metadata": {}}}})
    out = tools.dispatch("web_read", {"url": "https://shop", "extract": "the price"})
    assert '"price": "$9"' in out or '"price":"$9"' in out
    log = (tmp_path / "logs" / "web-actions.log").read_text()
    assert "read+extract" in log and "https://shop" in log


def test_map_returns_url_list(monkeypatch):
    _stub(monkeypatch, {("POST", "/map"): {"success": True, "links": [
        {"url": "https://s/a"}, {"url": "https://s/b"}]}})
    out = tools.dispatch("web_map", {"url": "https://s"})
    assert json.loads(out) == ["https://s/a", "https://s/b"]


def test_crawl_submits_and_logs(tmp_path, monkeypatch):
    _stub(monkeypatch, {("POST", "/crawl"): {"success": True, "id": "job-123", "url": "u"}})
    out = tools.dispatch("web_crawl", {"url": "https://s", "limit": 500})
    assert json.loads(out)["job_id"] == "job-123"
    log = (tmp_path / "logs" / "web-actions.log").read_text()
    assert "crawl" in log and "https://s" in log
    # limit clamped to 100 in the request
    # (checked via the log detail containing "limit 100")
    assert "limit 100" in log


def test_crawl_result_polls_until_done(monkeypatch):
    calls = {"n": 0}

    def status(method, path, body):
        calls["n"] += 1
        if calls["n"] < 2:
            return {"success": True, "status": "scraping", "completed": 0, "total": 2, "data": []}
        return {"success": True, "status": "completed", "completed": 2, "total": 2,
                "creditsUsed": 2, "data": [
                    {"markdown": "page one", "metadata": {"sourceURL": "https://s/1"}},
                    {"markdown": "page two", "metadata": {"sourceURL": "https://s/2"}}]}

    monkeypatch.setattr(web, "_request", lambda m, p, body=None: status(m, p, body))
    monkeypatch.setattr(web.time, "sleep", lambda s: None)
    out = tools.dispatch("web_crawl_result", {"job_id": "j", "max_pages": 5})
    assert out.startswith("[web content")
    assert "page one" in out and "page two" in out
    assert "2/2 pages" in out


def test_api_error_becomes_a_string(monkeypatch):
    _stub(monkeypatch, {("POST", "/search"): {"error": "HTTP 401"}})
    out = tools.dispatch("web_search", {"query": "x"})
    assert out == "error: HTTP 401"


def test_request_http_error_becomes_error_dict(monkeypatch):
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(401, {"error": "bad key"}))
    assert web._request("POST", "/search", {}) == {"error": "bad key"}


def test_request_success_false_becomes_error_dict(monkeypatch):
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(200, {"success": False, "error": "quota"}))
    assert web._request("POST", "/search", {}) == {"error": "quota"}


def test_request_non_json_body_becomes_error_dict(monkeypatch):
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(502, text_body="<html>bad gateway</html>"))
    d = web._request("POST", "/search", {})
    assert "error" in d and "502" in d["error"]


def test_request_non_dict_json_body_becomes_error_dict(monkeypatch):
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(200, ["not", "a", "dict"]))
    d = web._request("POST", "/search", {})
    assert "error" in d


def test_request_transport_error_becomes_error_dict(monkeypatch):
    import httpx
    def boom(*a, **k): raise httpx.ConnectError("no route")
    monkeypatch.setattr(web.httpx, "request", boom)
    d = web._request("POST", "/search", {})
    assert "error" in d and "network" in d["error"].lower()


def test_request_never_raises_on_a_non_httperror(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("Authorization: Bearer fc-secret leaked in message")
    monkeypatch.setattr(web.httpx, "request", boom)
    d = web._request("POST", "/search", {})
    assert "error" in d
    assert "fc-secret" not in d["error"] and "RuntimeError" in d["error"]


def test_crawl_result_returns_partial_on_deadline(monkeypatch):
    monkeypatch.setattr(web, "CRAWL_POLL_BUDGET", 0)
    _stub(monkeypatch, {("GET", "/crawl"): {
        "success": True, "status": "scraping", "completed": 1, "total": 5,
        "data": [{"markdown": "one so far", "metadata": {"sourceURL": "https://s/1"}}]}})
    out = tools.dispatch("web_crawl_result", {"job_id": "j"})
    assert out.startswith("[web content")
    assert "status: scraping" in out and "one so far" in out


def test_crawl_result_handles_failed_status(monkeypatch):
    _stub(monkeypatch, {("GET", "/crawl"): {
        "success": True, "status": "failed", "completed": 0, "total": 0, "data": []}})
    out = tools.dispatch("web_crawl_result", {"job_id": "j"})
    assert "status: failed" in out


def test_crawl_include_exclude_map_to_firecrawl_fields(monkeypatch):
    seen = _stub(monkeypatch, {("POST", "/crawl"): {"success": True, "id": "j", "url": "u"}})
    tools.dispatch("web_crawl", {"url": "https://s", "include": ["/docs/*"], "exclude": ["/blog/*"]})
    body = seen[0][2]
    assert body["includePaths"] == ["/docs/*"] and body["excludePaths"] == ["/blog/*"]


def test_web_read_without_extract_writes_no_log(tmp_path, monkeypatch):
    _stub(monkeypatch, {("POST", "/scrape"): {"success": True, "data": {"markdown": "hi", "metadata": {}}}})
    tools.dispatch("web_read", {"url": "https://x"})
    assert not (tmp_path / "logs" / "web-actions.log").exists()


def test_map_clamps_limit(monkeypatch):
    seen = _stub(monkeypatch, {("POST", "/map"): {"success": True, "links": []}})
    tools.dispatch("web_map", {"url": "https://s", "limit": 9999})
    assert seen[0][2]["limit"] == 200


def test_non_search_tools_also_report_not_configured(tmp_path):
    tools.reset(); web.configure(tmp_path, ""); web.register()
    for name, args in [("web_read", {"url": "u"}), ("web_map", {"url": "u"}),
                       ("web_crawl", {"url": "u"}), ("web_crawl_result", {"job_id": "j"})]:
        out = tools.dispatch(name, args)
        assert out.startswith("error:") and "not configured" in out
