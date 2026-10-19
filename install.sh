#!/data/data/com.termux/files/usr/bin/sh
# Caelza — one-line install for Termux (the headless Body on a phone).
#
#   curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/install.sh | sh
#
# What it does, in order:
#   1. installs the Termux packages the Body needs
#   2. clones (or updates) the repo to $CAELZA_DIR  (default ~/caelza)
#   3. pip-installs the Body package
#   4. hands off to `python scripts/setup.py`, which walks the steps that need
#      a human (battery whitelist, MiniMax login, ADB pairing, Telegram token)
#
# Flags / env:
#   CAELZA_DIR=~/somewhere      checkout location
#   CAELZA_REF=main             branch or tag to install
#   CAELZA_NO_SETUP=1           clone + install only; run setup.py yourself later
#
# Requirements: Termux, Termux:API and Termux:Boot from F-Droid (not the Play
# Store build). Re-running is safe; every step is idempotent.
set -eu

REPO="${CAELZA_REPO:-https://github.com/Enlightened-Republic/caelza}"
DIR="${CAELZA_DIR:-$HOME/caelza}"
REF="${CAELZA_REF:-main}"

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

case "${PREFIX:-}" in
  */com.termux/*) ;;
  *) die "this installer is for Termux on Android. On a hub or laptop use the Runtime: see runtime/README.md" ;;
esac

say "installing packages"
pkg install -y python nodejs git openssh termux-api android-tools >/dev/null

if [ -d "$DIR/.git" ]; then
  say "updating $DIR"
  git -C "$DIR" fetch -q origin "$REF"
  git -C "$DIR" checkout -q "$REF" 2>/dev/null || git -C "$DIR" checkout -q -B "$REF" "origin/$REF"
  git -C "$DIR" pull -q --ff-only origin "$REF" || true
else
  say "cloning $REPO → $DIR"
  git clone -q --branch "$REF" "$REPO" "$DIR"
fi

say "installing the Body package"
pip install -q -e "$DIR" 2>/dev/null || pip install -q --break-system-packages -e "$DIR"

if [ ! -f "$DIR/caelza_body/agent/prompt.md" ]; then
  cp "$DIR/caelza_body/agent/prompt.example.md" "$DIR/caelza_body/agent/prompt.md"
  say "wrote caelza_body/agent/prompt.md from the template — edit it (name, owner, purpose)"
fi

if [ "${CAELZA_NO_SETUP:-0}" = "1" ]; then
  say "done. Next: cd $DIR && python scripts/setup.py"
  exit 0
fi

say "handing off to setup (the steps that need you)"
cd "$DIR"
exec python scripts/setup.py
