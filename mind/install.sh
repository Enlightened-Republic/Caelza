#!/usr/bin/env sh
# Caelza Mind — install xanima-server, the brain service, from a Caelza release.
# Termux on a phone, or a Linux hub (x86_64 or aarch64).
#
#   curl -fsSL https://raw.githubusercontent.com/Enlightened-Republic/caelza/main/mind/install.sh | sh
#
# What it does, in order:
#   1. finds the release (latest, or $CAELZA_VERSION) and its caelza-mind-<ver>.tgz
#      asset through the GitHub API, downloads it, checks the .sha256 beside it
#   2. installs it under ~/.local/share/caelza/mind with `npm install --omit=dev`
#      (the service's two native sqlite modules come prebuilt for Linux x86_64
#      and aarch64; Termux builds them, which is what clang and make are for)
#   3. writes the `caelza-mind` launcher ($PREFIX/bin on Termux, ~/.local/bin
#      elsewhere) and, with CAELZA_SERVICE=1, what starts it after a reboot
#      (a Termux:Boot script, or a systemd user unit on a hub)
#   4. prints the next steps: serve, mint the tokens, point the Runtime at it
#
# Flags / env:
#   CAELZA_VERSION=v0.2.0        a specific release tag (default: the latest release)
#   CAELZA_ARCHIVE=~/x.tgz       install from a tarball you already have; no network
#   CAELZA_MIND_DIR=...          where it lands (default ~/.local/share/caelza/mind)
#   CAELZA_BIN_DIR=...           where the launcher goes
#   CAELZA_SERVICE=1             also install the boot script / systemd user unit
#   GITHUB_TOKEN=ghp_...         required while the repo is private (API + asset download)
#
# The Runtime is a separate install (runtime/termux-install.sh, or the release
# tarball for your hub); the Body is ../install.sh. Re-running is safe: a newer
# release replaces the install in place, the brains under ~/.xanima are never touched.
set -eu

REPO="${CAELZA_GH_REPO:-Enlightened-Republic/caelza}"
API="https://api.github.com/repos/$REPO/releases"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/caelza"
MIND_DIR="${CAELZA_MIND_DIR:-$DATA_DIR/mind}"

say() { printf '\033[1;36m[caelza-mind]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza-mind] error:\033[0m %s\n' "$*" >&2; exit 1; }

termux=0
case "${PREFIX:-}" in */com.termux/*) termux=1 ;; esac
if [ "$termux" = 1 ]; then
  BIN_DIR="${CAELZA_BIN_DIR:-$PREFIX/bin}"
  say "installing packages (node, and what the native sqlite modules build with)"
  pkg install -y nodejs python make clang pkg-config >/dev/null
else
  BIN_DIR="${CAELZA_BIN_DIR:-$HOME/.local/bin}"
  [ "$(uname -s)" = "Linux" ] || die "this installer is for Linux and Termux; elsewhere: npm install --omit=dev <caelza-mind-*.tgz> and run node_modules/xanima-server/dist/cli.js"
  command -v node >/dev/null 2>&1 || die "node >= 22 is required: https://nodejs.org or your package manager"
  command -v npm >/dev/null 2>&1 || die "npm is required (it comes with node)"
fi
command -v curl >/dev/null 2>&1 || die "curl is required"
command -v tar >/dev/null 2>&1 || die "tar is required"
node -e 'const [m] = process.versions.node.split(".").map(Number); process.exit(m >= 22 ? 0 : 1)' \
  || die "node $(node --version) is too old; xanima-server needs node >= 22"
NODE="$(command -v node)"

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
    || die "could not read the release. Private repo? export GITHUB_TOKEN=<token with repo read>. No release yet? ask for a v* tag to be pushed, or pack one yourself: mind/pack.sh"
  # The Mind's tarball sits beside the Runtime's -<target>.tar.gz archives and the APK;
  # it is the one named caelza-mind-<version>.tgz, with its .sha256 beside it.
  cat > "$work/pick.js" <<'EOF'
const fs = require("node:fs");
const rel = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const assets = rel.assets || [];
const tgz = assets.find((a) => /^caelza-mind-.+\.tgz$/.test(a.name));
if (!tgz) {
  console.error(`release ${rel.tag_name} has no caelza-mind-<version>.tgz asset (the Mind's pack may have been skipped; see the release's workflow log)`);
  process.exit(1);
}
const sum = assets.find((a) => a.name === tgz.name + ".sha256");
console.log(rel.tag_name || "");
console.log(tgz.name);
console.log(tgz.url);
console.log(sum ? sum.url : "");
EOF
  "$NODE" "$work/pick.js" "$work/release.json" > "$work/asset" || exit 1
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

tar -tzf "$archive" | grep -x 'package/dist/cli.js' >/dev/null || die "$archive is not a caelza-mind tarball (no package/dist/cli.js inside)"

mkdir -p "$MIND_DIR"
# A minimal project around the install, so npm has somewhere to put node_modules
# and the tarball stays beside it as the record of what is installed.
[ -f "$MIND_DIR/package.json" ] || printf '{\n  "name": "caelza-mind",\n  "private": true,\n  "description": "the Caelza Mind: xanima-server, installed by mind/install.sh"\n}\n' > "$MIND_DIR/package.json"
cp -f "$archive" "$MIND_DIR/caelza-mind.tgz"
say "installing into $MIND_DIR (npm install --omit=dev; the native sqlite modules can take a minute)"
(cd "$MIND_DIR" && npm install --omit=dev --no-save --no-audit --no-fund --loglevel=error ./caelza-mind.tgz) \
  || die "npm install failed. On Termux the native modules need: pkg install clang make python pkg-config; on a hub, node >= 22 and a network path to registry.npmjs.org"
cli="$MIND_DIR/node_modules/xanima-server/dist/cli.js"
[ -f "$cli" ] || die "the install left no $cli"

mkdir -p "$BIN_DIR"
cat > "$BIN_DIR/caelza-mind" <<EOF
#!/usr/bin/env sh
# Caelza Mind: xanima-server, installed by mind/install.sh into $MIND_DIR
exec "$NODE" "$cli" "\$@"
EOF
chmod 755 "$BIN_DIR/caelza-mind"
say "launcher → $BIN_DIR/caelza-mind"
case ":$PATH:" in
  *":$BIN_DIR:"*) ;;
  *) say "$BIN_DIR is not on your PATH yet (add it, or call the launcher by its path)" ;;
esac

if [ "${CAELZA_SERVICE:-0}" = "1" ]; then
  mkdir -p "$MIND_DIR/logs"
  if [ "$termux" = 1 ]; then
    mkdir -p "$HOME/.termux/boot"
    cat > "$HOME/.termux/boot/caelza-mind" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot — start the Caelza Mind (xanima-server, the brain service) after a reboot.
termux-wake-lock
exec "$BIN_DIR/caelza-mind" serve >> "$MIND_DIR/logs/service.log" 2>&1
EOF
    chmod +x "$HOME/.termux/boot/caelza-mind"
    say "boot script → ~/.termux/boot/caelza-mind (needs Termux:Boot from F-Droid)"
  else
    unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    mkdir -p "$unit_dir"
    cat > "$unit_dir/caelza-mind.service" <<EOF
[Unit]
Description=Caelza Mind (xanima-server, the brain service on 127.0.0.1:18790)
After=network.target

[Service]
ExecStart=$BIN_DIR/caelza-mind serve
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
    say "systemd user unit → $unit_dir/caelza-mind.service"
    if command -v systemctl >/dev/null 2>&1 && systemctl --user daemon-reload 2>/dev/null; then
      systemctl --user enable --now caelza-mind.service >/dev/null 2>&1 \
        && say "service enabled and started (systemctl --user status caelza-mind; loginctl enable-linger $(id -un) keeps it up after you log out)" \
        || say "could not enable the unit (systemctl --user enable --now caelza-mind.service once a user session is up)"
    else
      say "no user systemd here; start it yourself: caelza-mind serve"
    fi
  fi
fi

say "$("$BIN_DIR/caelza-mind" --help 2>/dev/null | head -1 || echo 'installed (version check failed; try: caelza-mind --help)')"
cat <<EOF

Next:
  caelza-mind serve                               # the brain service on http://127.0.0.1:18790 (or CAELZA_SERVICE=1 above)
  mkdir -p ~/.xanima/tokens
  caelza-mind token mint --agent main --scopes read,write --json | jq -r .token > ~/.xanima/tokens/main.token
  caelza-mind token mint --agent provisioner --scopes provision --json | jq -r .token > ~/.xanima/tokens/provision.token
  caelza config set memory.backend xanima         # the Runtime's own memory is the brain service (mind/caelza-mind.example.toml has the full block)
  caelza memory stats                             # the smoke test
EOF
