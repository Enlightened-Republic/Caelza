from niba.agent.redact import Redactor


def test_scrub_replaces_secret():
    r = Redactor(["tg-secret-token"])
    assert r.scrub("bot tg-secret-token ok") == "bot «redacted» ok"


def test_short_values_ignored():
    r = Redactor(["abc"])
    assert r.scrub("abc def") == "abc def"


def test_scrub_obj_recurses():
    r = Redactor(["SEKRIT-VALUE"])
    out = r.scrub_obj({"a": ["x SEKRIT-VALUE", {"b": "SEKRIT-VALUE"}]})
    assert out == {"a": ["x «redacted»", {"b": "«redacted»"}]}
