#!/bin/sh
# Caelza — connect Home Assistant (lights, switches, thermostats, locks).
#
#   sh scripts/home-connect.sh [URL]       # add Home Assistant's MCP server and ask for a token
#   sh scripts/home-connect.sh --dry-run   # only show what it would write
#
# URL is your Home Assistant address (default http://homeassistant.local:8123).
# Home Assistant's own MCP server decides what Caelza sees: only entities you
# exposed to voice assistants. The token is asked at a masked prompt, so it is
# never on a command line, in shell history or in a log. Config produced:
# runtime/caelza.homeassistant.example.toml. UNVERIFIED against a live Home
# Assistant: see that file's note about token auth.
#
# Env:  CAELZA_CONFIG_DIR (default ~/.caelza), CAELZA_AGENT (default main)
set -eu

CFG="${CAELZA_CONFIG_DIR:-$HOME/.caelza}"
AGENT="${CAELZA_AGENT:-main}"
DRY=0
BASE="http://homeassistant.local:8123"
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    http://*|https://*) BASE="${a%/}" ;;
    *) printf 'unknown argument: %s\n' "$a" >&2; exit 2 ;;
  esac
done
URL="$BASE/api/mcp/assist"

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

say "Home Assistant MCP server: $URL  ->  agent '$AGENT'  (config $CFG)"
if [ "$DRY" = 1 ]; then
  say "would set mcp.servers.homeassistant.{transport=http, url, tool_timeout_secs=30}"
  say "would ask for mcp.servers.homeassistant.headers.Authorization (masked) and add 'homeassistant' to agents.$AGENT.mcp_bundles"
  exit 0
fi

command -v caelza >/dev/null 2>&1 || die "caelza is not on PATH; install the Runtime first, or merge runtime/caelza.homeassistant.example.toml by hand"
[ -t 0 ] && [ -t 2 ] || die "the token prompt needs a terminal; run this in Termux or a shell, not from a pipe"

cset() { caelza --config-dir "$CFG" config set "$1" "$2" >/dev/null || die "caelza config set $1 failed"; }

cat >&2 <<'EOF'

Before the next step, in Home Assistant (needs version 2025.2 or newer):
  1. Settings > System > AI: turn the Model Context Protocol Server on.
  2. Expose the devices Caelza may use to voice assistants (Settings > Voice assistants > Expose).
  3. Your profile (bottom left) > Security > Long-lived access tokens > Create, and copy it.
At the prompt type:  Bearer <your token>

EOF

cset mcp.servers.homeassistant.transport http
cset mcp.servers.homeassistant.url "$URL"
cset mcp.servers.homeassistant.tool_timeout_secs 30
say "server written; now the token (masked)"
caelza --config-dir "$CFG" config set mcp.servers.homeassistant.headers.Authorization \
  || die "the token was not saved; re-run this script"

if cset mcp_bundles.homeassistant.servers '["homeassistant"]' 2>/dev/null; then
  say "bundle 'homeassistant' written"
else
  say "add this by hand (see runtime/caelza.homeassistant.example.toml):  [mcp_bundles.homeassistant]  servers = [\"homeassistant\"]"
fi
say "last step: add \"homeassistant\" to agents.$AGENT.mcp_bundles, then restart: caelza daemon"
say "check: ask $AGENT \"which lights are on?\" — a first, harmless read. Locks and doors always ask first."
