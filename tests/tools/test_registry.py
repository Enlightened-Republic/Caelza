import pytest
from caelza_body.agent import tools


@pytest.fixture(autouse=True)
def _clean():
    tools.reset()
    yield
    tools.reset()


def test_register_and_schema():
    @tools.tool("echo", "echo back", {"type": "object", "properties": {"x": {"type": "string"}}})
    def echo(x): return x
    s = tools.schemas()[0]
    assert s == {"type": "function", "function": {
        "name": "echo", "description": "echo back",
        "parameters": {"type": "object", "properties": {"x": {"type": "string"}}}}}


def test_dispatch_json_encodes_non_strings():
    @tools.tool("nums", "d", {"type": "object", "properties": {}})
    def nums(): return {"a": 1}
    assert tools.dispatch("nums", {}) == '{"a": 1}'


def test_dispatch_unknown_tool():
    assert tools.dispatch("nope", {}) == "error: unknown tool nope"


def test_dispatch_catches_exceptions():
    @tools.tool("boom", "d", {"type": "object", "properties": {}})
    def boom(): raise ValueError("bad")
    assert tools.dispatch("boom", {}) == "error: ValueError: bad"


def test_reset_clears_pending_media():
    from caelza_body.agent.tools import media
    media.emit_image("/tmp/x.jpg", "image/jpeg")
    tools.reset()
    assert media.PENDING_MEDIA == []
