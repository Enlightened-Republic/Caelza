import json

import pytest

from caelza_body.agent import tools
from caelza_body.agent.tools import web


@pytest.fixture(autouse=True)
def _cfg(tmp_path, monkeypatch):
    tools.reset()
    # Force the ddg provider off unless a test opts in — a CI box with `ddgs`
    # installed must not make real DuckDuckGo calls in the auto-mode tests.
    monkeypatch.setattr(web, "DDGS", None)
    web.configure(tmp_path, firecrawl_key="fc-testkey")
    web.register()
    yield
    tools.reset()
    web.configure(tmp_path, firecrawl_key="")


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


def test_no_provider_configured_is_a_clean_error(tmp_path, monkeypatch):
    tools.reset()
    web.configure(tmp_path, firecrawl_key="")
    monkeypatch.setattr(web, "DDGS", None)
    web.register()
    out = tools.dispatch("web_search", {"query": "x"})
    assert out.startswith("error:") and "all search providers failed" in out


def test_search_returns_normalised_object(monkeypatch):
    _stub(monkeypatch, {("POST", "/search"): {"success": True, "data": {"web": [
        {"title": "A", "url": "https://a", "description": "da"},
        {"title": "B", "url": "https://b", "description": "db"}]}}})
    out = json.loads(tools.dispatch("web_search", {"query": "hello", "limit": 2}))
    assert out["provider"] == "firecrawl"
    assert [r["url"] for r in out["results"]] == ["https://a", "https://b"]


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


def test_named_provider_error_becomes_a_string(monkeypatch):
    _stub(monkeypatch, {("POST", "/search"): {"error": "HTTP 401"}})
    out = tools.dispatch("web_search", {"query": "x", "provider": "firecrawl"})
    assert out.startswith("error:") and "firecrawl" in out


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
    tools.reset(); web.configure(tmp_path, firecrawl_key=""); web.register()
    for name, args in [("web_read", {"url": "u"}), ("web_map", {"url": "u"}),
                       ("web_crawl", {"url": "u"}), ("web_crawl_result", {"job_id": "j"})]:
        out = tools.dispatch(name, args)
        assert out.startswith("error:") and "not configured" in out


# --- multi-provider web_search -------------------------------------------------

def test_search_tavily_normalises(tmp_path, monkeypatch):
    tools.reset()
    web.configure(tmp_path, firecrawl_key="", tavily_key="tvly-x")
    web.register()

    def fake(method, url, **kw):
        return _resp(200, {"answer": "A synthesized answer.",
                           "results": [{"title": "T", "url": "https://u",
                                        "content": "body text"}]})
    monkeypatch.setattr(web.httpx, "request", fake)
    out = json.loads(tools.dispatch("web_search", {"query": "x", "provider": "tavily"}))
    assert out["provider"] == "tavily"
    assert out["answer"] == "A synthesized answer."
    assert out["results"][0] == {"title": "T", "url": "https://u", "description": "body text"}


def test_search_searchapi_normalises(tmp_path, monkeypatch):
    tools.reset()
    web.configure(tmp_path, searchapi_key="sa-x")
    web.register()
    monkeypatch.setattr(web.httpx, "request", lambda m, u, **k: _resp(200, {
        "organic_results": [{"title": "T2", "link": "https://u2", "snippet": "snip"}]}))
    out = json.loads(tools.dispatch("web_search", {"query": "x", "provider": "searchapi"}))
    assert out["provider"] == "searchapi"
    assert out["results"][0] == {"title": "T2", "url": "https://u2", "description": "snip"}


def test_search_auto_falls_through_to_next_provider(tmp_path, monkeypatch):
    """tavily 500 -> searchapi ok. auto must not stop at the first failure."""
    tools.reset()
    web.configure(tmp_path, firecrawl_key="fc", tavily_key="tv", searchapi_key="sa")
    web.register()

    def fake(method, url, **kw):
        if "tavily" in url:
            return _resp(500, {"detail": "server error"})
        if "searchapi" in url:
            return _resp(200, {"organic_results": [{"title": "S", "link": "https://s",
                                                    "snippet": "z"}]})
        return _resp(200, {})
    monkeypatch.setattr(web.httpx, "request", fake)
    out = json.loads(tools.dispatch("web_search", {"query": "x"}))  # provider=auto
    assert out["provider"] == "searchapi" and out["results"][0]["url"] == "https://s"


def test_search_auto_skips_unconfigured_providers(tmp_path, monkeypatch):
    """only firecrawl configured -> auto goes straight to it, no tavily/searchapi calls."""
    tools.reset()
    web.configure(tmp_path, firecrawl_key="fc")
    web.register()
    calls = []

    def fake(method, url, **kw):
        calls.append(url)
        if "firecrawl" in url:
            return _resp(200, {"data": {"web": [{"title": "F", "url": "https://f",
                                                 "description": "d"}]}})
        return _resp(200, {})
    monkeypatch.setattr(web.httpx, "request", fake)
    out = json.loads(tools.dispatch("web_search", {"query": "x"}))
    assert out["provider"] == "firecrawl"
    assert all("tavily" not in u and "searchapi" not in u for u in calls)


def test_search_ddg_unavailable_is_a_clean_error(tmp_path, monkeypatch):
    tools.reset(); web.configure(tmp_path); web.register()
    monkeypatch.setattr(web, "DDGS", None)
    out = tools.dispatch("web_search", {"query": "x", "provider": "ddg"})
    assert out.startswith("error:") and "ddg" in out
    assert "pip install" not in out  # never tell a self-modifying agent to pip install


def test_search_auto_chain_excludes_ddg_when_unavailable(tmp_path, monkeypatch):
    tools.reset(); web.configure(tmp_path, tavily_key="tv"); web.register()
    monkeypatch.setattr(web, "DDGS", None)
    assert web._auto_chain() == ("tavily", "searchapi", "firecrawl")
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(500, {"x": 1}))
    named = tools.dispatch("web_search", {"query": "x", "provider": "ddg"})
    allfail = tools.dispatch("web_search", {"query": "x"})
    assert "pip install" not in named and "pip install" not in allfail
    # and ddg is back in the chain when the lib is present
    monkeypatch.setattr(web, "DDGS", object())
    assert web._auto_chain() == ("tavily", "searchapi", "firecrawl", "ddg")


def test_search_failure_is_logged_without_leaking_key(tmp_path, monkeypatch):
    tools.reset()
    web.configure(tmp_path, tavily_key="tvly-secret")
    web.register()
    monkeypatch.setattr(web, "DDGS", None)

    def boom(*a, **k):
        raise RuntimeError("Authorization: Bearer tvly-secret")
    monkeypatch.setattr(web.httpx, "request", boom)
    out = tools.dispatch("web_search", {"query": "x", "provider": "tavily"})
    assert out.startswith("error:")
    log = (tmp_path / "logs" / "web-actions.log").read_text()
    assert "search-fail" in log and "tavily: RuntimeError" in log
    assert "tvly-secret" not in log


def test_search_ddg_via_lib(tmp_path, monkeypatch):
    tools.reset(); web.configure(tmp_path); web.register()

    class FakeDDGS:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def text(self, q, max_results=5):
            return [{"title": "D", "href": "https://d", "body": "dd"}]
    monkeypatch.setattr(web, "DDGS", FakeDDGS)
    out = json.loads(tools.dispatch("web_search", {"query": "x", "provider": "ddg"}))
    assert out["provider"] == "ddg" and out["results"][0]["url"] == "https://d"


def test_search_all_providers_fail(tmp_path, monkeypatch):
    tools.reset(); web.configure(tmp_path, tavily_key="tv"); web.register()
    monkeypatch.setattr(web.httpx, "request", lambda *a, **k: _resp(500, {"detail": "x"}))
    monkeypatch.setattr(web, "DDGS", None)
    out = tools.dispatch("web_search", {"query": "x"})
    assert out.startswith("error: all search providers failed")
