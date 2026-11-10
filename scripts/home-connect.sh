#!/bin/sh
# Caelza — connect Home Assistant (lights, switches, thermostats, locks).
#
#   sh scripts/home-connect.sh [URL]       # add Home Assistant's MCP server and ask for a token
#   sh scripts/home-connect.sh --dry-run   # only show what it would write
#
# URL is your Home Assistant address (default http://homeassistant.local:8123).
# The dashboard's Connect page does the same from a browser; this is the shell
# way. Home Assistant's own MCP server decides what Caelza sees: only entities
# you exposed to voice assistants. The `[[mcp.servers]]` row is a keyed list
# entry, which no `caelza config set` path can create, so the row, its bundle
# and the agent's grant land in one `caelza config patch` (one write, validated
# as a whole, the agent's other bundles kept); the token is asked at a masked
# prompt, so it is never on a command line, in shell history or in a log.
# Config produced: runtime/caelza.homeassistant.example.toml. UNVERIFIED
# against a live Home Assistant: see that file's note about token auth.
#
# Env:  CAELZA_CONFIG_DIR (default ~/.caelza), CAELZA_AGENT (default main)
set -eu

CFG="${CAELZA_CONFIG_DIR:-$HOME/.caelza}"
AGENT="${CAELZA_AGENT:-main}"
NAME="homeassistant"
TIMEOUT=30
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
  say "would patch mcp.servers.$NAME.{url, transport=http, tool_timeout_secs=$TIMEOUT}, mcp_bundles.$NAME.servers and agents.$AGENT.mcp_bundles in one write"
  say "would ask for mcp.servers.$NAME.headers.Authorization (masked)"
  exit 0
fi

command -v caelza >/dev/null 2>&1 || die "caelza is not on PATH; install the Runtime first, or use the dashboard's Connect page, or merge runtime/caelza.homeassistant.example.toml by hand"
[ -t 0 ] && [ -t 2 ] || die "the token prompt needs a terminal; run this in Termux or a shell, not from a pipe"

have=$(caelza --config-dir "$CFG" config get "agents.$AGENT.mcp_bundles" 2>/dev/null | tr -d '[]" \r' | tr ',' '\n' | grep -v '^$' || true)
merged=$(printf '%s\n%s\n' "$have" "$NAME" | awk 'NF && !seen[$0]++ { printf "%s\"%s\"", (n++ ? "," : ""), $0 }')

cat >&2 <<'EOF'

Before the next step, in Home Assistant (needs version 2025.2 or newer):
  1. Settings > System > AI: turn the Model Context Protocol Server on.
  2. Expose the devices Caelza may use to voice assistants (Settings > Voice assistants > Expose).
  3. Your profile (bottom left) > Security > Long-lived access tokens > Create, and copy it.
At the prompt type:  Bearer <your token>

EOF

caelza --config-dir "$CFG" config patch - >/dev/null <<EOF || die "caelza config patch failed; the config was not changed"
[
  {"op": "add", "path": "/mcp/servers/$NAME/url", "value": "$URL"},
  {"op": "add", "path": "/mcp/servers/$NAME/transport", "value": "http"},
  {"op": "add", "path": "/mcp/servers/$NAME/tool_timeout_secs", "value": $TIMEOUT},
  {"op": "add", "path": "/mcp_bundles/$NAME/servers", "value": ["$NAME"]},
  {"op": "add", "path": "/agents/$AGENT/mcp_bundles", "value": [$merged]}
]
EOF
say "server, bundle and the grant to '$AGENT' written; now the token (masked)"
caelza --config-dir "$CFG" config set "mcp.servers.$NAME.headers.Authorization" \
  || die "the token was not saved; re-run this script"
say "done. Restart the Runtime (caelza daemon) so '$AGENT' picks it up."
say "check: ask $AGENT \"which lights are on?\" — a first, harmless read. Locks and doors always ask first."
