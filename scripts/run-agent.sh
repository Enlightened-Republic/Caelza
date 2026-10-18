#!/data/data/com.termux/files/usr/bin/sh
cd "$(dirname "$0")/.."
exec python -m caelza_body.agent "$@"
