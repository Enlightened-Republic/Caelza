#!/bin/sh
# Caelza — connect the owner's apps through Maton (https://maton.ai).
#
#   sh scripts/maton-connect.sh            # add Maton's MCP server and ask for the key
#   sh scripts/maton-connect.sh --dry-run  # only show what it would write
#
# The dashboard's Connect page does the same from a browser; this is the shell
# way. Maton keeps the OAuth to Gmail, Calendar, Drive, Notion, Slack, HubSpot
# and about a hundred more; Caelza keeps one Maton API key. The `[[mcp.servers]]`
# row is a keyed list entry, which no `caelza config set` path can create
# (`mcp.servers.maton.url` is "Unknown property" until the row exists), so the
# row, its bundle and the agent's grant land in one `caelza config patch` (one
# write, validated as a whole, the agent's other bundles kept); then the key is
# asked at a masked prompt, so it is never on a command line, in shell history
# or in a log. The config it produces is runtime/caelza.maton.example.toml.
#
# Env:
#   CAELZA_CONFIG_DIR=...   the Runtime config dir (default ~/.caelza)
#   CAELZA_AGENT=main       the agent that gets the apps (default main)
# Re-running is safe: it sets the same values again.
set -eu

CFG="${CAELZA_CONFIG_DIR:-$HOME/.caelza}"
AGENT="${CAELZA_AGENT:-main}"
NAME="maton"
URL="https://mcp.maton.ai"
TIMEOUT=60
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

say "Maton MCP server: $URL  ->  agent '$AGENT'  (config $CFG)"
if [ "$DRY" = 1 ]; then
  say "would patch mcp.servers.$NAME.{url, transport=http, tool_timeout_secs=$TIMEOUT}, mcp_bundles.$NAME.servers and agents.$AGENT.mcp_bundles in one write"
  say "would ask for mcp.servers.$NAME.headers.Authorization (masked)"
  exit 0
fi

command -v caelza >/dev/null 2>&1 || die "caelza is not on PATH; install the Runtime first (the Caelza app does this), or use the dashboard's Connect page, or merge runtime/caelza.maton.example.toml by hand"
[ -t 0 ] && [ -t 2 ] || die "the key prompt needs a terminal; run this in Termux or a shell, not from a pipe"
case "$AGENT" in ""|*[!A-Za-z0-9_-]*) die "CAELZA_AGENT must be one word of letters, digits, _ and - (got '$AGENT')" ;; esac
# While the Runtime runs it owns the config: the CLI refuses a patch that touches an
# agent then, and a file written behind it drifts until a restart. So: stopped first.
[ -S "$CFG/data/daemon.sock" ] && die "the Runtime is running ($CFG/data/daemon.sock answers). Stop it first (Ctrl+C in its window, or stop the app's service) and re-run; or use the dashboard's Connect page, which works while it runs"

# The agent's bundle list with this one added once: `config get` prints the
# array as JSON (`[]`, `["mind", "body"]`), which is one line of names here.
have=$(caelza --config-dir "$CFG" config get "agents.$AGENT.mcp_bundles" 2>/dev/null | tr -d '[]" \r' | tr ',' '\n' | grep -v '^$' || true)
merged=$(printf '%s\n%s\n' "$have" "$NAME" | awk 'NF && !seen[$0]++ { printf "%s\"%s\"", (n++ ? "," : ""), $0 }')

cat >&2 <<'EOF'

Before the next step you need a Maton account (free to make) at https://maton.ai.
Connect the apps you want there (Google, Notion, Slack...), then copy your API key
from your Maton account settings. At the prompt type:  Bearer <your key>

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
say "server, bundle and the grant to '$AGENT' written; now the key (masked)"
caelza --config-dir "$CFG" config set "mcp.servers.$NAME.headers.Authorization" \
  || die "the key was not saved; re-run this script"
say "done. Restart the Runtime (caelza daemon) so '$AGENT' picks it up."
say "check: ask Cael or $AGENT \"what is on my calendar today?\" — a first, harmless read."
