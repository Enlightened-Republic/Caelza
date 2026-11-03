#!/data/data/com.termux/files/usr/bin/sh
# Caelza Runtime — install the aarch64-linux-android release build in Termux.
#
#   curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/runtime/termux-install.sh | sh
#
# What it does, in order:
#   1. finds the release (latest, or $CAELZA_VERSION) and its
#      caelza-<ver>-aarch64-linux-android.tar.gz asset through the GitHub API
#   2. downloads it, checks the .sha256 the release workflow published, extracts
#   3. installs `caelza` to $PREFIX/bin and the web dashboard to
#      ~/.local/share/caelza/web/dist (one of the places the gateway looks)
#   4. prints `caelza --version` and the next steps
#
# Flags / env:
#   CAELZA_VERSION=v0.1.0       a specific release tag (default: the latest release)
#   GITHUB_TOKEN=ghp_...        required while the repo is private (API + asset download)
#   CAELZA_ARCHIVE=~/x.tar.gz   install from a tarball you already have; no network
#   CAELZA_BOOT=1               also write ~/.termux/boot/caelza-runtime (Termux:Boot
#                               starts `caelza daemon` after a reboot)
#
# The Body (sensors, ADB, the supervisor) is a separate install: ../install.sh.
# Once the Body is installed, `caelza-body runtime update` fetches the same
# release under the supervisor's guard (verified, probed, last-good kept,
# rolled back on a crash loop) and `caelza-body runtime link` points
# $PREFIX/bin/caelza at it; this script is the plain, unguarded install.
# Re-running is safe; every step is idempotent.
set -eu

REPO="${CAELZA_GH_REPO:-Enlightened-Republic/caelza}"
TARGET="aarch64-linux-android"
API="https://api.github.com/repos/$REPO/releases"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/caelza"

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

case "${PREFIX:-}" in
  */com.termux/*) ;;
  *) die "this installer is for Termux on Android. Elsewhere, download the release archive for your platform or run runtime/build.sh" ;;
esac
[ "$(uname -m)" = "aarch64" ] || die "this phone is $(uname -m); only 64-bit ARM (aarch64) has a prebuilt Caelza. Build from source: runtime/README.md"

need() { command -v "$1" >/dev/null 2>&1 || pkg install -y "$2" >/dev/null; }
need curl curl
need tar tar
need python3 python

auth() { [ -n "${GITHUB_TOKEN:-}" ] && printf 'Authorization: token %s' "$GITHUB_TOKEN" || printf 'X-Caelza: anonymous'; }

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

if [ -n "${CAELZA_ARCHIVE:-}" ]; then
  archive="$CAELZA_ARCHIVE"
  [ -f "$archive" ] || die "no such file: $archive"
  say "installing from $archive"
else
  if [ -n "${CAELZA_VERSION:-}" ]; then url="$API/tags/$CAELZA_VERSION"; else url="$API/latest"; fi
  say "looking up the release ($url)"
  curl -fsSL -H "$(auth)" -H 'Accept: application/vnd.github+json' "$url" > "$work/release.json" \
    || die "could not read the release. Private repo? export GITHUB_TOKEN=<token with repo read>. No release yet? ask for a v* tag to be pushed, or build from source"
  python3 - "$work/release.json" "$TARGET" > "$work/asset" <<'EOF'
import json, sys
rel = json.load(open(sys.argv[1]))
suffix = f"-{sys.argv[2]}.tar.gz"
assets = {a["name"]: a for a in rel.get("assets", [])}
tar = next((a for n, a in assets.items() if n.endswith(suffix)), None)
if tar is None:
    sys.exit(f"release {rel.get('tag_name')} has no {suffix} asset (the Android build is experimental and may have been skipped)")
sha = assets.get(tar["name"] + ".sha256")
print(rel.get("tag_name", ""))
print(tar["name"])
print(tar["url"])
print(sha["url"] if sha else "")
EOF
  tag="$(sed -n 1p "$work/asset")"; name="$(sed -n 2p "$work/asset")"
  asset_url="$(sed -n 3p "$work/asset")"; sha_url="$(sed -n 4p "$work/asset")"
  say "downloading $name ($tag)"
  curl -fsSL -H "$(auth)" -H 'Accept: application/octet-stream' -o "$work/$name" "$asset_url"
  if [ -n "$sha_url" ]; then
    curl -fsSL -H "$(auth)" -H 'Accept: application/octet-stream' -o "$work/$name.sha256" "$sha_url"
    (cd "$work" && sha256sum -c "$name.sha256" >/dev/null) || die "checksum mismatch for $name"
    say "checksum ok"
  else
    say "no .sha256 published for $name; skipping the checksum"
  fi
  archive="$work/$name"
fi

mkdir -p "$work/x"
tar -xzf "$archive" -C "$work/x"
top="$(find "$work/x" -mindepth 1 -maxdepth 1 -type d | head -1)"
[ -x "$top/caelza" ] || die "archive has no caelza binary"

install -m 755 "$top/caelza" "$PREFIX/bin/caelza"
say "installed $PREFIX/bin/caelza"
if [ -d "$top/web/dist" ]; then
  rm -rf "$DATA_DIR/web/dist"; mkdir -p "$DATA_DIR/web"
  cp -r "$top/web/dist" "$DATA_DIR/web/dist"
  say "dashboard → $DATA_DIR/web/dist"
fi
mkdir -p "$DATA_DIR"
for f in NOTICE UPSTREAM.md LICENSE-MIT LICENSE-APACHE; do [ -f "$top/$f" ] && cp "$top/$f" "$DATA_DIR/$f"; done

if [ "${CAELZA_BOOT:-0}" = "1" ]; then
  mkdir -p "$HOME/.termux/boot" "$HOME/.caelza/logs"
  cat > "$HOME/.termux/boot/caelza-runtime" <<'EOF'
#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot — start the Caelza runtime (gateway + channels + cron) after a reboot.
# Once the Body's guard holds a Runtime (`caelza-body runtime update`), the
# supervisor runs it; a second daemon would only fight it for the port.
[ -e "$HOME/.caelza-body/runtime/current" ] && exit 0
termux-wake-lock
exec caelza daemon >> "$HOME/.caelza/logs/daemon.log" 2>&1
EOF
  chmod +x "$HOME/.termux/boot/caelza-runtime"
  say "boot script → ~/.termux/boot/caelza-runtime (needs Termux:Boot from F-Droid)"
fi

say "$(caelza --version 2>/dev/null || echo 'caelza installed (version check failed; try: caelza --version)')"
cat <<EOF

Next:
  caelza quickstart                       # pick a model provider, create the first agent
  caelza config set channels.telegram.home.bot_token   # if you want Telegram (masked prompt)
  curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/mind/install.sh | sh   # the Mind (xanima-server) from the same release → caelza-mind
  # then merge runtime/caelza.phone.example.toml into ~/.caelza/config.toml:
  #   Telegram alias + peer group, the Mind (xanima) and Body (caelza-body) MCP servers,
  #   the risk profile that gates the dangerous Body tools, and [sop] sops_dir
  caelza-body playbooks --install         # the phone playbooks → ~/.caelza/shared/sops (needs ../install.sh)
  caelza daemon                           # gateway on http://127.0.0.1:42617 + channels
EOF
[ -d "$HOME/caelza" ] && say "the example configs are in $HOME/caelza/runtime, mind and body" || true
