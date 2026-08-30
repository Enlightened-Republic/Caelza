#!/data/data/com.termux/files/usr/bin/python
"""`niba setup` — first-boot bring-up for a fresh Termux install (spec §12 / §14.0 Phase C).

Run inside Termux on the phone that will host Niba::

    python scripts/setup.py            # walk every step
    python scripts/setup.py --dry-run  # print the plan and exit

The pure helpers (`pkg_install`, `sharpwave_install`, `mcp_install`) just return
the shell command(s) they would run — `run()` is what actually executes them, so
they stay unit-testable. The rest do a single concrete side effect (a file write,
one `input()` prompt, one `sh()` call) and are exercised on the real phone.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import httpx

# --- niba home resolution -------------------------------------------------

DEFAULT_NIBA_HOME = Path.home() / ".niba"


def _home(niba_home=None) -> Path:
    if niba_home is not None:
        return Path(niba_home)
    return Path(os.environ.get("NIBA_HOME", DEFAULT_NIBA_HOME))


def sh(cmd, **kwargs):
    """Central execution point. One shell command; inherits stdio (interactive
    tools like `mmx auth login` need a real terminal). Tests monkeypatch this."""
    import subprocess

    return subprocess.run(cmd, shell=True, **kwargs)


# --- pure helpers: return the command(s) run() should execute -------------

def pkg_install():
    return "pkg install -y python nodejs git openssh termux-api android-tools"


def sharpwave_install():
    return [
        "npm i -g --allow-scripts=better-sqlite3 sharpwave",
        'termux-fix-shebang "$(command -v sharpwave)"',
    ]


def mcp_install():
    return 'pip install "mcp>=1.0,<2" httpx'


# --- side-effecting steps ------------------------------------------------

def grant_perms():
    """Set up shared storage and tell the owner which app perms termux-api needs."""
    sh("termux-setup-storage")
    print(
        "\nGrant these to Termux:API in Android Settings -> Apps -> Termux:API "
        "-> Permissions:\n"
        "  - Camera\n"
        "  - Microphone\n"
        "  - Location\n"
        "  - Storage\n"
    )


def write_config(telegram_token, owner_chat_id, openrouter_key, niba_home=None):
    """Write `<niba_home>/config.toml` in the exact shape `niba.agent.config` loads."""
    home = _home(niba_home)
    home.mkdir(parents=True, exist_ok=True)
    # TOML *literal* strings (single-quoted): no escaping, so a token that
    # contains a backslash or double-quote can't produce an unparseable config.
    text = (
        "[telegram]\n"
        f"bot_token = '{telegram_token}'\n"
        f"owner_chat_id = {int(owner_chat_id)}\n"
        "[openrouter]\n"
        f"api_key = '{openrouter_key}'\n"
        "[minimax]\n"
        'mmx_config_path = "~/.mmx/config.json"\n'
        "[limits]\n"
        "model_calls_per_hour = 120\n"
        "monthly_token_budget = 1600000000\n"
    )
    path = home / "config.toml"
    path.write_text(text)
    print(f"wrote {path}")


def mmx_login():
    """Launch the interactive MiniMax login; the human completes the browser step."""
    sh("mmx auth login")
    mmx_cfg = Path("~/.mmx/config.json").expanduser()
    if mmx_cfg.exists():
        print(f"ok: {mmx_cfg} exists")
    else:
        print(f"WARNING: {mmx_cfg} not found — `mmx auth login` may not have completed")


def pair_self_adb(niba_home=None):
    """Pair Termux's adb to this phone over Wireless debugging; store the port.

    Wireless debugging shows a *pairing* host:port + code under "Pair device with
    pairing code", and a separate always-on debug port on the main screen. We
    pair with the former and persist the latter for `niba.agent.adb`.
    """
    home = _home(niba_home)
    print(
        "\nOn this phone: Settings -> Developer options -> Wireless debugging -> ON.\n"
        "Open 'Pair device with pairing code' and keep that dialog visible.\n"
    )
    pair_hostport = input("pairing host:port (from the pairing dialog): ").strip()
    code = input("6-digit pairing code: ").strip()
    debug_port = input("wireless-debugging port (main screen, NOT the pairing port): ").strip()

    sh(f"adb pair {pair_hostport} {code}")
    sh(f"adb connect 127.0.0.1:{debug_port}")

    run_dir = home / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    port_file = run_dir / "adb-self-port"
    port_file.write_text(debug_port)
    print(f"wrote {port_file} = {debug_port}")


def boot_script() -> str:
    """The Termux:Boot script, with this checkout's absolute path baked in so a
    reboot doesn't depend on the repo living at exactly `~/niba`."""
    repo = Path(__file__).resolve().parents[1]
    return (
        "#!/data/data/com.termux/files/usr/bin/sh\n"
        "termux-wake-lock\n"
        "export NIBA_HOME=$HOME/.niba\n"
        # adb needs a writable TMPDIR for its server socket/logs; Termux:Boot's
        # env doesn't set one.
        "export TMPDIR=$PREFIX/tmp\n"
        "mkdir -p $HOME/.niba/logs $TMPDIR\n"
        f'cd "{repo}" || exit 1\n'
        "exec python -m niba.supervisor >> $HOME/.niba/logs/supervisor.out 2>&1\n"
    )


def install_boot_script():
    """Write `~/.termux/boot/niba` — Termux:Boot runs it on device boot."""
    boot = Path.home() / ".termux" / "boot" / "niba"
    boot.parent.mkdir(parents=True, exist_ok=True)
    boot.write_text(boot_script())
    try:
        boot.chmod(0o755)
    except OSError:
        pass
    print(f"wrote {boot}")


def capture_owner_chat_id(telegram_token, *, attempts=150, delay=2.0):
    """Poll getUpdates until the owner messages the bot; return that chat id.

    Bounded so a test can monkeypatch httpx and so a wrong token can't hang
    setup forever (~5 min at the defaults).
    """
    url = f"https://api.telegram.org/bot{telegram_token}/getUpdates"
    print("Send any message to your bot from Telegram now...")
    for _ in range(attempts):
        try:
            data = httpx.get(url, timeout=30).json()
        except httpx.HTTPError:
            time.sleep(delay)
            continue
        for upd in data.get("result", []):
            msg = upd.get("message") or upd.get("edited_message")
            chat_id = (msg or {}).get("chat", {}).get("id")
            if chat_id is not None:
                print(f"captured owner_chat_id = {chat_id}")
                return int(chat_id)
        time.sleep(delay)
    raise TimeoutError("no message reached the bot — check the token and try again")


def configure_niba(niba_home=None):
    """[prompt] Collect the Telegram/OpenRouter secrets and write config.toml."""
    telegram_token = input("Telegram bot token: ").strip()
    openrouter_key = input("OpenRouter API key (blank to skip): ").strip()
    owner_chat_id = capture_owner_chat_id(telegram_token)
    write_config(telegram_token, owner_chat_id, openrouter_key, niba_home=niba_home)


def battery_unrestrict():
    """[prompt] Exempt Termux from Android battery optimisation (spec §12 step 4).

    Without this Android kills Termux in the background, which defeats
    Termux:Boot and the wake-lock entirely. The printed instruction is the
    contract; the intent below is a best-effort shortcut to the right screen.
    """
    print(
        "\nExempt Termux from battery optimisation — otherwise Android kills it\n"
        "in the background and the boot script / wake-lock do nothing:\n"
        "  Settings -> Apps -> Termux -> Battery -> Unrestricted\n"
        "(and the same for Termux:API and Termux:Boot if listed)\n"
    )
    sh("am start -a android.settings.IGNORE_BATTERY_OPTIMIZATION_SETTINGS")


def verify():
    """[prompt] Final step (spec §12 step 11): prove the thing we configured runs."""
    print(
        "\nSetup complete. Now start the supervisor and confirm it works:\n"
        "  python -m niba.supervisor        (or just reboot the phone)\n"
        "Then send your bot a message on Telegram and check Niba replies.\n"
    )


# --- step sequencing ---------------------------------------------------

#: (name, kind, callable). kind:
#:   "cmds"   — fn() returns shell command string(s); run() executes them
#:   "auto"   — fn() does its own side effect unattended, returns None
#:   "prompt" — like "auto" but waits for the human first, returns None
#: Only "cmds" steps ever hand anything to sh() via _exec_result — a step that
#: returns a *path* (boot script, port file) must NOT be executed.
# tailscale up and the repo `git clone` / `pip install -e .` are deliberately
# NOT here — they are bootstrap-before-setup (you can't `python scripts/setup.py`
# without the clone). See the plan's "Deferred from niba setup" note.
STEPS = [
    ("pkg_install", "cmds", pkg_install),
    ("sharpwave_install", "cmds", sharpwave_install),
    ("mcp_install", "cmds", mcp_install),
    ("grant_perms", "auto", grant_perms),
    ("battery_unrestrict", "prompt", battery_unrestrict),
    ("mmx_login", "prompt", mmx_login),
    ("pair_self_adb", "prompt", pair_self_adb),
    ("configure_niba", "prompt", configure_niba),
    ("install_boot_script", "auto", install_boot_script),
    ("verify", "prompt", verify),
]


def _exec_result(result):
    """A "cmds" step returned command string(s) -> run them via sh()."""
    if result is None:
        return
    cmds = [result] if isinstance(result, str) else list(result)
    for cmd in cmds:
        print(f"  $ {cmd}")
        sh(cmd)


def run(dry_run=False):
    for name, kind, fn in STEPS:
        print(f"[{kind}] {name}")
        if dry_run:
            continue
        if kind == "prompt":
            input(f"  {name}: press Enter when you are ready for this step...")
        result = fn()
        if kind == "cmds":
            _exec_result(result)
    if dry_run:
        print("\n(dry run - nothing executed)")
    return 0


if __name__ == "__main__":
    sys.exit(run(dry_run="--dry-run" in sys.argv[1:]))
