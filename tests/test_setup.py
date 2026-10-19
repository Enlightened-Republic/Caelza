"""Task 9: `scripts/setup.py` pure-helper coverage + the `--dry-run` plan.

The interactive `run()` path is genuinely interactive (Android toggles, browser
logins); the real test is running it on phone #2. Here we cover the pure
helpers and the dry-run plan listing.
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
import setup  # noqa: E402


def test_write_config(tmp_path, monkeypatch):
    monkeypatch.setenv("CAELZA_BODY_HOME", str(tmp_path))
    setup.write_config("TG", 42, "OR", body_home=tmp_path)
    text = (tmp_path / "config.toml").read_text()
    assert "bot_token = 'TG'" in text and "owner_chat_id = 42" in text and "api_key = 'OR'" in text


def test_write_config_is_valid_toml_the_agent_can_load(tmp_path):
    import tomllib

    setup.write_config("TG", 42, "OR", body_home=tmp_path)
    data = tomllib.loads((tmp_path / "config.toml").read_text())
    assert data["telegram"]["bot_token"] == "TG"
    assert data["telegram"]["owner_chat_id"] == 42  # unquoted int
    assert data["openrouter"]["api_key"] == "OR"
    assert data["minimax"]["mmx_config_path"] == "~/.mmx/config.json"
    assert data["limits"]["model_calls_per_hour"] == 120
    assert data["limits"]["monthly_token_budget"] == 1_600_000_000


def test_write_config_includes_firecrawl(tmp_path):
    import tomllib

    setup.write_config("TG", 42, "OR", "fc-xyz", body_home=tmp_path)
    text = (tmp_path / "config.toml").read_text()
    assert "[firecrawl]" in text and "api_key = 'fc-xyz'" in text
    # still valid TOML the agent can load
    assert tomllib.loads(text)["firecrawl"]["api_key"] == "fc-xyz"


def test_write_config_firecrawl_optional(tmp_path):
    import tomllib

    setup.write_config("TG", 42, "OR", body_home=tmp_path)  # no firecrawl arg
    d = tomllib.loads((tmp_path / "config.toml").read_text())
    assert d.get("firecrawl", {}).get("api_key", "") == ""


def test_write_config_includes_tavily_and_searchapi(tmp_path):
    import tomllib
    setup.write_config("TG", 42, "OR", "fc", "tv", "sa", body_home=tmp_path)
    d = tomllib.loads((tmp_path / "config.toml").read_text())
    assert d["tavily"]["api_key"] == "tv" and d["searchapi"]["api_key"] == "sa"


def test_dry_run_lists_steps():
    out = subprocess.run([sys.executable, "scripts/setup.py", "--dry-run"],
                         capture_output=True, text=True)
    assert "pkg_install" in out.stdout and "mmx_login" in out.stdout
    assert out.returncode == 0


def test_pkg_install_returns_the_command_without_running_it():
    cmd = setup.pkg_install()
    assert "pkg install -y python nodejs git openssh termux-api android-tools" in (
        cmd if isinstance(cmd, str) else " ".join(cmd)
    )


def test_pair_self_adb_writes_the_self_port_file(tmp_path, monkeypatch):
    answers = iter(["127.0.0.1:37000", "123456", "42585"])
    monkeypatch.setattr("builtins.input", lambda *a, **k: next(answers))
    ran = []
    monkeypatch.setattr(setup, "sh", lambda cmd, **k: ran.append(cmd))

    setup.pair_self_adb(body_home=tmp_path)

    assert (tmp_path / "run" / "adb-self-port").read_text().strip() == "42585"
    assert any("adb pair 127.0.0.1:37000 123456" in c for c in ran)


def test_grant_perms_reports_failures(tmp_path, monkeypatch, capsys):
    """I3: every `pm grant` failing must not print success."""
    port = tmp_path / "run" / "adb-self-port"
    port.parent.mkdir(parents=True)
    port.write_text("42585")

    class FakeCP:
        returncode = 1

    monkeypatch.setattr(setup, "sh", lambda cmd, **k: FakeCP())
    setup.grant_perms(body_home=tmp_path)
    out = capsys.readouterr().out
    assert "WARNING" in out
    assert "CAMERA" in out and "ACCESS_FINE_LOCATION" in out


def test_grant_perms_manual_when_no_self_adb(tmp_path, monkeypatch, capsys):
    """No port file -> print the by-hand instructions, don't touch adb."""
    ran = []
    monkeypatch.setattr(setup, "sh", lambda cmd, **k: ran.append(cmd))
    setup.grant_perms(body_home=tmp_path)
    out = capsys.readouterr().out
    assert "Android Settings" in out and "Camera" in out
    assert not any("pm grant" in c for c in ran)


def test_grant_perms_manual_when_port_is_not_a_number(tmp_path, monkeypatch, capsys):
    """M1: a garbage port file falls back to the manual branch, not a shell call."""
    port = tmp_path / "run" / "adb-self-port"
    port.parent.mkdir(parents=True)
    port.write_text("not-a-port")
    ran = []
    monkeypatch.setattr(setup, "sh", lambda cmd, **k: ran.append(cmd))
    setup.grant_perms(body_home=tmp_path)
    out = capsys.readouterr().out
    assert "Android Settings" in out
    assert not any("pm grant" in c for c in ran)


def test_install_boot_script_writes_an_executable_boot_file(tmp_path, monkeypatch):
    monkeypatch.setattr(setup.Path, "home", staticmethod(lambda: tmp_path))

    setup.install_boot_script()

    boot = tmp_path / ".termux" / "boot" / "caelza-body"
    text = boot.read_text()
    assert text.startswith("#!")
    assert "caelza_body.supervisor" in text
    assert "termux-wake-lock" in text
    # I7: bakes this checkout's absolute path + fails loudly if the cd fails
    repo = str(Path(setup.__file__).resolve().parents[1])
    assert f'cd "{repo}" || exit 1' in text
    assert "export CAELZA_BODY_HOME=$HOME/.caelza-body" in text
    assert "export TMPDIR=$PREFIX/tmp" in text  # adb needs a writable TMPDIR
    # executable-ish: at least one exec bit set (best-effort on Windows)
    import os
    import stat

    mode = os.stat(boot).st_mode
    assert mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) or os.name == "nt"


def test_battery_and_verify_steps_are_present():
    names = [s[0] for s in setup.STEPS]
    assert "battery_unrestrict" in names  # spec §12 step 4
    assert names[-1] == "verify"          # spec §12 step 11


def test_steps_are_ordered_name_kind_callable():
    names = [s[0] for s in setup.STEPS]
    assert names[0] == "pkg_install"
    for name, kind, fn in setup.STEPS:
        assert kind in ("auto", "prompt", "cmds")
        assert callable(fn)


def test_run_executes_only_real_commands(tmp_path, monkeypatch):
    """C1: run() must never hand a filesystem path to sh() — only the "cmds"
    installer steps return anything executable."""
    monkeypatch.setenv("CAELZA_BODY_HOME", str(tmp_path))
    monkeypatch.setattr(setup.Path, "home", staticmethod(lambda: tmp_path))
    monkeypatch.setattr("builtins.input", lambda *a, **k: "")
    monkeypatch.setattr(setup, "capture_owner_chat_id", lambda *a, **k: 42)
    ran = []
    monkeypatch.setattr(setup, "sh", lambda cmd, **k: ran.append(cmd))

    assert setup.run(dry_run=False) == 0

    assert ran, "expected the installer steps to run"
    for cmd in ran:
        assert "/.termux/boot/" not in cmd and ".termux\\boot" not in cmd
        assert "adb-self-port" not in cmd
        assert "caelza_body.supervisor" not in cmd
        assert str(tmp_path) not in cmd
    # the boot script itself was still written (as a file, not executed)
    assert (tmp_path / ".termux" / "boot" / "caelza-body").exists()
