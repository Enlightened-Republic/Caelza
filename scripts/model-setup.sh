#!/bin/sh
# Caelza — the free local model: DeepSeek R1 on this device, and Cael the guide.
#
#   sh scripts/model-setup.sh            # detect, fetch the models, configure the Runtime, create Cael
#   sh scripts/model-setup.sh --dry-run  # only show what it would pick
#
# Where the Runtime runs decides the runner (scripts/model_ladder.py):
#   Termux (a phone)      llama.cpp from the Termux package; GGUFs under ~/.caelza/models;
#                         ~/.caelza/models/serve.sh runs llama-server on 127.0.0.1:8080,
#                         which is where the Runtime's llamacpp provider looks
#   Linux hub / laptop    Ollama (must be installed; the official installer is printed if not)
# The agent gets the biggest build the RAM allows; Cael always gets the 1.5B.
# Everything the Runtime needs is written with `caelza config set` when `caelza`
# is on PATH, otherwise the TOML to merge is runtime/caelza.local-model.example.toml.
#
# Env:
#   CAELZA_RAM_MB=7600         override detected RAM (the ladder's only input)
#   CAELZA_PLATFORM=termux     override detected platform (termux | linux)
#   CAELZA_MODELS_DIR=...      where GGUFs live (default ~/.caelza/models)
#   CAELZA_CONFIG_DIR=...      the Runtime config dir (default ~/.caelza)
#   CAELZA_BOOT=1              Termux: also write ~/.termux/boot/caelza-llama
#   CAELZA_SET_AGENT_MODEL=0   never touch agents.main.model_provider (default: set it only if empty)
# Re-running is safe; downloads resume and verified files are kept.
set -eu

HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/.." && pwd)
CFG="${CAELZA_CONFIG_DIR:-$HOME/.caelza}"
MODELS="${CAELZA_MODELS_DIR:-$CFG/models}"
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

if ! command -v python3 >/dev/null 2>&1; then
  case "${PREFIX:-}" in */com.termux/*) pkg install -y python >/dev/null ;; *) die "python3 is required (the ladder is scripts/model_ladder.py)" ;; esac
fi

ladder_args=""
[ -n "${CAELZA_RAM_MB:-}" ] && ladder_args="$ladder_args --ram-mb $CAELZA_RAM_MB"
[ -n "${CAELZA_PLATFORM:-}" ] && ladder_args="$ladder_args --platform $CAELZA_PLATFORM"
# shellcheck disable=SC2086
eval "$(python3 "$HERE/model_ladder.py" --shell $ladder_args)"

say "$PLATFORM, ${RAM_MB} MB RAM -> runner $RUNNER"
say "agent: $AGENT_NAME   guide (Cael): $GUIDE_NAME"
[ -n "$NOTES" ] && say "note: $NOTES"
[ "$DRY" = 1 ] && exit 0

# --- fetch a GGUF, resume-able, verified ------------------------------------
fetch_gguf() { # url file sha256 bytes
  url=$1; file=$2; sha=$3; bytes=$4
  dest="$MODELS/$file"
  if [ -f "$dest" ]; then
    if printf '%s  %s\n' "$sha" "$dest" | sha256sum -c --quiet - 2>/dev/null; then
      say "have $file (verified)"; return 0
    fi
    say "$file exists but does not verify; re-downloading"; rm -f "$dest"
  fi
  say "downloading $file ($((bytes / 1024 / 1024)) MiB) from Hugging Face"
  curl -fL --retry 5 --retry-delay 3 -C - -o "$dest.part" "$url"
  printf '%s  %s\n' "$sha" "$dest.part" | sha256sum -c --quiet - || die "checksum mismatch for $file"
  mv "$dest.part" "$dest"
  say "verified $file"
}

mkdir -p "$MODELS"
case "$RUNNER" in
  llamacpp)
    if ! command -v llama-server >/dev/null 2>&1; then
      case "${PREFIX:-}" in
        */com.termux/*) say "installing llama.cpp (Termux package llama-cpp)"; pkg install -y llama-cpp >/dev/null ;;
        *) die "llama-server not found. Install llama.cpp (https://github.com/ggml-org/llama.cpp) and put llama-server on PATH" ;;
      esac
    fi
    fetch_gguf "$GUIDE_URL" "$GUIDE_FILE" "$GUIDE_SHA256" "$GUIDE_BYTES"
    [ "$AGENT_FILE" != "$GUIDE_FILE" ] && fetch_gguf "$AGENT_URL" "$AGENT_FILE" "$AGENT_SHA256" "$AGENT_BYTES"
    threads=$(nproc 2>/dev/null || echo 4)
    cat > "$MODELS/serve.sh" <<EOF
#!/bin/sh
# llama-server for Caelza: the Runtime's llamacpp provider talks to http://localhost:8080/v1.
# Serves the agent model by default; \`serve.sh guide\` serves Cael's 1.5B instead.
# One server at a time on :8080. -c 4096 keeps a phone's memory in check.
set -eu
model="$MODELS/$AGENT_FILE"
[ "\${1:-}" = guide ] && model="$MODELS/$GUIDE_FILE"
exec llama-server -m "\$model" --host 127.0.0.1 --port 8080 -c 4096 --threads $threads "\$@"
EOF
    chmod +x "$MODELS/serve.sh"
    say "server script -> $MODELS/serve.sh"
    if [ "${CAELZA_BOOT:-0}" = 1 ] && [ -d "$HOME/.termux" ]; then
      mkdir -p "$HOME/.termux/boot" "$CFG/logs"
      cat > "$HOME/.termux/boot/caelza-llama" <<EOF
#!/data/data/com.termux/files/usr/bin/sh
# Termux:Boot — the local model server for Caelza (start it before caelza daemon).
termux-wake-lock
exec "$MODELS/serve.sh" >> "$CFG/logs/llama-server.log" 2>&1
EOF
      chmod +x "$HOME/.termux/boot/caelza-llama"
      say "boot script -> ~/.termux/boot/caelza-llama"
    fi
    ;;
  ollama)
    command -v ollama >/dev/null 2>&1 || die "Ollama is not installed. Install it first: curl -fsSL https://ollama.com/install.sh | sh   (then re-run this script)"
    say "pulling $AGENT_PULL"; ollama pull "$AGENT_PULL"
    if [ "$GUIDE_PULL" != "$AGENT_PULL" ]; then say "pulling $GUIDE_PULL (Cael)"; ollama pull "$GUIDE_PULL"; fi
    ;;
esac

# --- configure the Runtime ------------------------------------------------------
if command -v caelza >/dev/null 2>&1; then
  cset() { caelza --config-dir "$CFG" config set "$1" "$2" >/dev/null || die "caelza config set $1 failed"; }
  say "writing provider aliases $PROVIDER_AGENT and $PROVIDER_GUIDE"
  cset "providers.models.$RUNNER.local.model" "$AGENT_NAME"
  cset "providers.models.$RUNNER.guide.model" "$GUIDE_NAME"
  if [ "${CAELZA_SET_AGENT_MODEL:-1}" = 1 ]; then
    current=$(caelza --config-dir "$CFG" config get agents.main.model_provider 2>/dev/null | tail -n1 || true)
    case "$current" in
      ""|"<unset>"|*Unknown*) cset agents.main.model_provider "$PROVIDER_AGENT"; say "agents.main now runs on $PROVIDER_AGENT" ;;
      *) say "agents.main keeps model_provider = $current (set CAELZA_SET_AGENT_MODEL=1 and clear it to switch, or: caelza config set agents.main.model_provider $PROVIDER_AGENT)" ;;
    esac
  fi
  say "creating Cael (agents.cael, risk profile guide: readonly, no tools)"
  cset agents.cael.model_provider "$PROVIDER_GUIDE"
  cset agents.cael.risk_profile guide
  cset risk_profiles.guide.level readonly
  cset risk_profiles.guide.deny_all_tools true
else
  say "caelza is not on PATH: merge runtime/caelza.local-model.example.toml into $CFG/config.toml by hand"
fi

# --- Cael's persona -----------------------------------------------------------
ws="$CFG/agents/cael/workspace"
mkdir -p "$ws"
if [ ! -f "$ws/SOUL.md" ]; then
  cp "$ROOT/guide/cael.system.md" "$ws/SOUL.md"
  say "Cael's SOUL.md -> $ws/SOUL.md (from guide/cael.system.md)"
else
  say "Cael's SOUL.md exists; left as is (guide/cael.system.md is the source if you want to refresh it)"
fi
[ -f "$ws/IDENTITY.md" ] || cat > "$ws/IDENTITY.md" <<'EOF'
- **Name:** Cael
- **Role:** the guide inside Caelza; explains, never acts
- **Vibe:** plain, dry, confident; short declaratives; no exclamation marks
- **Made by:** Enlightened Republic
EOF

cat <<EOF

Done. Next:
EOF
if [ "$RUNNER" = llamacpp ]; then
  cat <<EOF
  $MODELS/serve.sh &            # start the local model (or CAELZA_BOOT=1 for Termux:Boot)
  curl -s http://127.0.0.1:8080/v1/models   # it answers when the model is loaded
EOF
fi
cat <<EOF
  caelza daemon                 # the agent (agents.main) and Cael (agents.cael) on the dashboard
  # bigger brain later: caelza quickstart --model-provider anthropic   (or openai, openrouter, ...)
  #   then caelza config set agents.main.model_provider <provider>.<alias>
EOF
