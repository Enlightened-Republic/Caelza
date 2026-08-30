import json
from pathlib import Path

from niba.agent.devices import DeviceRegistry


def test_add_get_all_remove(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("grandma", "192.168.1.9:5555", notes="her pixel")
    assert r.get("grandma")["host"] == "192.168.1.9:5555"
    assert "grandma" in r.all()
    r.remove("grandma")
    assert r.get("grandma") is None
    # persisted
    assert json.loads((tmp_path / "d.json").read_text()) == {}


def test_corrupt_file_starts_empty(tmp_path):
    (tmp_path / "d.json").write_text("{not json")
    assert DeviceRegistry(tmp_path / "d.json").all() == {}


def test_non_object_json_starts_empty(tmp_path):
    (tmp_path / "d.json").write_text("[1, 2]")
    assert DeviceRegistry(tmp_path / "d.json").all() == {}


def test_unreadable_path_starts_empty(tmp_path):
    # a directory where the file should be -> read_text raises OSError
    (tmp_path / "d.json").mkdir()
    assert DeviceRegistry(tmp_path / "d.json").all() == {}


def test_all_returns_a_copy(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("a", "h")
    got = r.all()
    got.pop("a", None)
    got["b"] = {"host": "x"}
    assert "a" in r.all() and "b" not in r.all()
    assert DeviceRegistry(tmp_path / "d.json").get("b") is None


def test_save_is_atomic_no_tmp_left_behind(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("a", "h")
    assert not (tmp_path / "d.json.tmp").exists()
    assert json.loads((tmp_path / "d.json").read_text())["a"]["host"] == "h"


def test_touch_updates_last_seen(tmp_path):
    r = DeviceRegistry(tmp_path / "d.json")
    r.add("x", "h")
    before = r.get("x")["last_seen"]
    import time

    time.sleep(0.01)
    r.touch("x")
    assert r.get("x")["last_seen"] >= before


def test_missing_file_starts_empty(tmp_path):
    """Missing file should start with empty registry, no exception."""
    r = DeviceRegistry(tmp_path / "nonexistent.json")
    assert r.all() == {}


def test_reload_from_disk_preserves_data(tmp_path):
    """Add data, create new instance, verify it persisted."""
    path = tmp_path / "d.json"
    r1 = DeviceRegistry(path)
    r1.add("device1", "192.168.1.1", notes="test")

    # Create new instance from same file
    r2 = DeviceRegistry(path)
    result = r2.get("device1")
    assert result is not None
    assert result["host"] == "192.168.1.1"
    assert result["notes"] == "test"


def test_remove_nonexistent_is_noop(tmp_path):
    """Removing unknown device should be idempotent."""
    r = DeviceRegistry(tmp_path / "d.json")
    r.remove("unknown")  # Should not raise
    assert r.all() == {}
