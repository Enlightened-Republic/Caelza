#!/bin/sh
# Caelza — connect the owner's apps through Maton (https://maton.ai).
#
#   sh scripts/maton-connect.sh            # add Maton's MCP server and ask for the key
#   sh scripts/maton-connect.sh --dry-run  # only show what it would write
#
# Maton keeps the OAuth to Gmail, Calendar, Drive, Notion, Slack, HubSpot and
# about a hundred more; Caelza keeps one Maton API key. This writes the server
# with `caelza config set` (the Runtime validates it) and then asks for the key
# at a masked prompt, so the key is never on a command line, in shell history or
# in a log. The config it produces is runtime/caelza.maton.example.toml.
#
# Env:
#   CAELZA_CONFIG_DIR=...   the Runtime config dir (default ~/.caelza)
#   CAELZA_AGENT=main       the agent that gets the apps (default main)
# Re-running is safe: it sets the same values again.
set -eu

CFG="${CAELZA_CONFIG_DIR:-$HOME/.caelza}"
AGENT="${CAELZA_AGENT:-main}"
URL="https://mcp.maton.ai"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

say "Maton MCP server: $URL  ->  agent '$AGENT'  (config $CFG)"
if [ "$DRY" = 1 ]; then
  say "would set mcp.servers.maton.{transport=http, url, tool_timeout_secs=60}"
  say "would ask for mcp.servers.maton.headers.Authorization (masked) and add 'maton' to agents.$AGENT.mcp_bundles"
  exit 0
fi

command -v caelza >/dev/null 2>&1 || die "caelza is not on PATH; install the Runtime first (the Caelza app does this), or merge runtime/caelza.maton.example.toml by hand"
[ -t 0 ] && [ -t 2 ] || die "the key prompt needs a terminal; run this in Termux or a shell, not from a pipe"

cset() { caelza --config-dir "$CFG" config set "$1" "$2" >/dev/null || die "caelza config set $1 failed"; }

cat >&2 <<'EOF'

Before the next step you need a Maton account (free to make) at https://maton.ai.
Connect the apps you want there (Google, Notion, Slack...), then copy your API key
from your Maton account settings. At the prompt type:  Bearer <your key>

EOF

cset mcp.servers.maton.transport http
cset mcp.servers.maton.url "$URL"
cset mcp.servers.maton.tool_timeout_secs 60
say "server written; now the key (masked)"
caelza --config-dir "$CFG" config set mcp.servers.maton.headers.Authorization \
  || die "the key was not saved; re-run this script"

# The bundle and the agent's list. Array values vary by Runtime version, so a
# failure here is a hint, not a stop: the server and key are already in place.
if cset mcp_bundles.maton.servers '["maton"]' 2>/dev/null; then
  say "bundle 'maton' written"
else
  say "add this by hand (see runtime/caelza.maton.example.toml):  [mcp_bundles.maton]  servers = [\"maton\"]"
fi
say "last step: add \"maton\" to agents.$AGENT.mcp_bundles (the dashboard's Config page, Agents, does this), then restart: caelza daemon"
say "check: ask Cael or $AGENT \"what is on my calendar today?\" — a first, harmless read."
