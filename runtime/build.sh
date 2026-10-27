#!/usr/bin/env bash
# runtime/build.sh — build the Caelza runtime from a pinned upstream ZeroClaw commit.
#
#   ./runtime/build.sh                 # fetch pin, rebrand, cargo build --release
#   ./runtime/build.sh --check-only    # fetch pin, rebrand, cargo check (fast CI gate)
#   ./runtime/build.sh --no-build      # just produce the rebranded tree
#   ./runtime/build.sh --from ~/src/zeroclaw   # reuse an existing checkout at the pin
#   ./runtime/build.sh --target aarch64-linux-android   # cross-build (NDK on PATH or $ANDROID_NDK_HOME)
#
# Pipeline: fetch → stage → rename paths → rename contents → theme map →
#           overlay → brand assets → patches → NOTICE → residual check → build.
# Everything it writes lives under runtime/.cache, runtime/.build, runtime/dist.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
CACHE="$HERE/.cache/upstream"
WORK="$HERE/.build/src"
DIST="$HERE/dist"
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HERE/.build/target}"

# Files that take the dashboard theme swap (theme-map.txt).
THEME_FILES=(
  web/src/index.css
  web/src/contexts/ThemeContext.tsx
  web/src/contexts/colorThemes.ts
  web/src/contexts/themes.json
)

usage() { sed -n '2,13p' "${BASH_SOURCE[0]}"; }
log()   { printf '\033[1;36m[caelza]\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m[caelza] error:\033[0m %s\n' "$*" >&2; exit 1; }

# Features beyond upstream's lean default: the git channel is Forge (the agent
# proposes Runtime changes as pull requests; docs/forge.md). The release
# workflow passes the same flag; `--features` overrides.
FROM=""; MODE="build"; JOBS=""; FEATURES="${CAELZA_FEATURES-channel-git}"; ALLOW_RESIDUAL=0; SKIP_ASSETS=0; TARGET=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --check-only) MODE="check"; shift ;;
    --no-build) MODE="none"; shift ;;
    --jobs) JOBS="$2"; shift 2 ;;
    --features) FEATURES="$2"; shift 2 ;;
    --target) TARGET="$2"; shift 2 ;;
    --allow-residual) ALLOW_RESIDUAL=1; shift ;;
    --skip-assets) SKIP_ASSETS=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "unknown flag: $1" ;;
  esac
done

# shellcheck source=brand.env
source "$HERE/brand.env"

toml_get() { sed -n -E "s/^$1[[:space:]]*=[[:space:]]*\"([^\"]*)\".*/\1/p" "$2" | head -1; }
UP_REPO="$(toml_get repo "$HERE/upstream.toml")"
UP_SHA="$(toml_get commit "$HERE/upstream.toml")"
UP_VERSION="$(toml_get version "$HERE/upstream.toml")"
[[ -n "$UP_REPO" && -n "$UP_SHA" ]] || die "upstream.toml needs repo and commit"

for tool in git perl tar cargo; do command -v "$tool" >/dev/null || die "missing tool: $tool"; done

RENAME="perl $HERE/lib/rename.pl"
EXCL_PATTERNS="$(mktemp)"; trap 'rm -f "$EXCL_PATTERNS"' EXIT
grep -v -E '^\s*(#|$)' "$HERE/exclude.txt" > "$EXCL_PATTERNS" || true

# --- 1. fetch -----------------------------------------------------------------
fetch_upstream() {
  if [[ -n "$FROM" ]]; then
    [[ -d "$FROM/.git" ]] || die "--from must point at a git checkout"
    local have; have="$(git -C "$FROM" rev-parse HEAD)"
    [[ "$have" == "$UP_SHA" ]] || die "--from is at $have but upstream.toml pins $UP_SHA"
    SRC="$FROM"; log "using checkout $SRC"; return
  fi
  mkdir -p "$CACHE"
  if [[ ! -d "$CACHE/.git" ]]; then
    git -C "$CACHE" init -q
    git -C "$CACHE" remote add origin "$UP_REPO"
  fi
  if [[ "$(git -C "$CACHE" rev-parse HEAD 2>/dev/null || true)" != "$UP_SHA" ]]; then
    log "fetching $UP_REPO @ $UP_SHA"
    git -C "$CACHE" fetch -q --depth 1 origin "$UP_SHA"
    git -C "$CACHE" checkout -q --detach FETCH_HEAD
  fi
  SRC="$CACHE"
}

# --- 2. stage -----------------------------------------------------------------
stage() {
  rm -rf "$WORK"; mkdir -p "$WORK"
  log "staging upstream tree → $WORK"
  (cd "$SRC" && tar --exclude=./.git --exclude=./target --exclude=./web/node_modules -cf - .) \
    | (cd "$WORK" && tar -xf -)
}

# --- 3. rename paths ----------------------------------------------------------
rename_paths() {
  log "renaming paths"
  local n=0
  # -depth: children before parents, so a renamed directory never orphans a pending child.
  while IFS= read -r p; do
    local base dir new
    base="$(basename "$p")"; dir="$(dirname "$p")"
    new="$(printf '%s' "$base" | $RENAME "$HERE/rename-map.txt" "$HERE/protect.txt")"
    if [[ "$new" != "$base" ]]; then mv "$p" "$dir/$new"; n=$((n+1)); fi
  done < <(find "$WORK" -depth -iname '*zeroclaw*' -o -depth -iname '*zerocode*' -o -depth -iname '*zerorelay*')
  log "renamed $n paths"
}

# --- 4. rename contents -------------------------------------------------------
rename_contents() {
  log "rewriting brand tokens in text files"
  local list; list="$(mktemp)"
  (cd "$WORK" && grep -rIl --exclude-dir=.git \
      -E 'zeroclaw|ZeroClaw|ZEROCLAW|Zeroclaw|zerocode|ZeroCode|Zerocode|ZEROCODE|zerorelay|ZeroRelay|Zerorelay|ZERORELAY|Zero Claw|zero_claw|zeroclawlabs' . \
    | grep -v -F -f "$EXCL_PATTERNS" > "$list") || true
  (cd "$WORK" && xargs -a "$list" -r -d '\n' $RENAME "$HERE/rename-map.txt" "$HERE/protect.txt")
  log "rewrote $(wc -l < "$list") files"
  rm -f "$list"
}

# --- 5. theme map -------------------------------------------------------------
apply_theme() {
  log "applying dashboard theme map"
  local f
  for f in "${THEME_FILES[@]}"; do
    [[ -f "$WORK/$f" ]] && $RENAME "$HERE/theme-map.txt" /dev/null "$WORK/$f"
  done
  if command -v python3 >/dev/null; then
    log "registering caelza-dark / caelza-light as the dashboard defaults"
    python3 "$HERE/lib/dashboard_theme.py" "$WORK" "$ROOT/brand/tokens.json"
  else
    log "python3 missing: dashboard default theme entries skipped"
  fi
}

# --- 6. overlay + 7. brand assets + 8. patches --------------------------------
apply_overlay() {
  if [[ -d "$HERE/overlay" ]] && [[ -n "$(ls -A "$HERE/overlay")" ]]; then
    log "copying overlay files"
    (cd "$HERE/overlay" && find . -type f -print0) | while IFS= read -r -d '' f; do
      mkdir -p "$WORK/$(dirname "$f")"; cp "$HERE/overlay/$f" "$WORK/$f"
    done
  fi
}

apply_assets() {
  [[ "$SKIP_ASSETS" == 1 ]] && { log "skipping brand assets"; return; }
  command -v python3 >/dev/null || die "python3 (with Pillow) is needed for brand assets; pass --skip-assets to bypass"
  log "rendering brand assets into the tree"
  python3 "$ROOT/brand/make_assets.py" --runtime "$WORK"
}

apply_patches() {
  local p; shopt -s nullglob
  for p in "$HERE"/patches/*.patch; do
    log "applying $(basename "$p")"
    (cd "$WORK" && patch -p1 --no-backup-if-mismatch --forward < "$p")
  done
  shopt -u nullglob
}

# --- 9. NOTICE / provenance ---------------------------------------------------
write_notice() {
  log "writing fork NOTICE + UPSTREAM.md"
  local orig; orig="$(cat "$WORK/NOTICE")"
  cat > "$WORK/NOTICE" <<EOF
$CAELZA_PRODUCT
Copyright 2026 $CAELZA_ORG
$CAELZA_ORG_TM presents $CAELZA_PRODUCT. $CAELZA_SITE

$CAELZA_PRODUCT is a rebranded build of ZeroClaw, redistributed under the same
dual licence (MIT OR Apache-2.0). It is not affiliated with or endorsed by
ZeroClaw Labs; "ZeroClaw" and the ZeroClaw logo are their trademarks and are
not used by this distribution. Upstream copyright and notices follow verbatim.

  Upstream: $UP_REPO
  Commit:   $UP_SHA (v$UP_VERSION)
  Fork:     $CAELZA_REPO

===============================================================================
Original upstream NOTICE
===============================================================================

$orig
EOF
  cat > "$WORK/UPSTREAM.md" <<EOF
# Upstream provenance

This tree was generated by \`runtime/build.sh\` in $CAELZA_REPO from:

| | |
|---|---|
| Upstream | $UP_REPO |
| Commit | \`$UP_SHA\` |
| Upstream version | $UP_VERSION |
| Generated | $(date -u +%Y-%m-%dT%H:%M:%SZ) |

Do not edit this tree by hand; change the rename map, overlay, theme map or
patches under \`runtime/\` and rebuild. The WASM plugin ABI namespace
\`zeroclaw:plugin@0.1.0\` is intentionally preserved for plugin compatibility.
EOF
}

# --- 10. residual check -------------------------------------------------------
check_residual() {
  log "checking for residual upstream brand tokens"
  local residual
  residual="$(cd "$WORK" && grep -rIlP --exclude-dir=.git \
      '(?i)zeroclaw(?!:plugin|::plugin)|(?i)zerocode|(?i)zerorelay' . \
    | grep -v -F -f "$EXCL_PATTERNS" || true)"
  if [[ -n "$residual" ]]; then
    printf '%s\n' "$residual" | sed 's/^/  residual: /'
    [[ "$ALLOW_RESIDUAL" == 1 ]] || die "residual brand tokens found (use --allow-residual to continue)"
  else
    log "no residual tokens outside the protected ABI namespace"
  fi
}

# --- 11. build ----------------------------------------------------------------
# Cross targets: cargo needs the target's linker (upstream's .cargo/config.toml
# names it) and the `cc` crate needs a C compiler for the bundled sqlite / ring.
# For Android both come from the NDK: put its llvm bin dir on PATH, or set
# ANDROID_NDK_HOME and this does it. The Rust std for the target must be
# installed (`rustup target add <triple>`).
prepare_target() {
  [[ -n "$TARGET" ]] || return 0
  rustup target list --installed 2>/dev/null | grep -qx "$TARGET" \
    || die "Rust target $TARGET is not installed: rustup target add $TARGET"
  case "$TARGET" in
    *-linux-android*)
      local api=21 arch="${TARGET%%-*}" clang
      [[ "$TARGET" == armv7-* ]] && arch="armv7a" && TARGET_EABI="eabi"
      clang="${arch}-linux-android${TARGET_EABI:-}${api}-clang"
      if ! command -v "$clang" >/dev/null && [[ -n "${ANDROID_NDK_HOME:-${ANDROID_NDK:-}}" ]]; then
        export PATH="${ANDROID_NDK_HOME:-$ANDROID_NDK}/toolchains/llvm/prebuilt/linux-x86_64/bin:$PATH"
      fi
      command -v "$clang" >/dev/null \
        || die "$clang not found: put the NDK's toolchains/llvm/prebuilt/*/bin on PATH or set ANDROID_NDK_HOME"
      local env_target="${TARGET//-/_}"
      export "CC_${env_target}=$clang" "CXX_${env_target}=${clang}++" "AR_${env_target}=llvm-ar"
      log "android toolchain: $clang"
      ;;
  esac
}

build() {
  export CAELZA_BUILD_ID="${CAELZA_BUILD_ID:-v${UP_VERSION}+zeroclaw.${UP_SHA:0:10}}"
  local jobs=() feat=() tgt=() outdir="$CARGO_TARGET_DIR/release" out="$CAELZA_BIN"
  [[ -n "$JOBS" ]] && jobs=(--jobs "$JOBS")
  [[ -n "$FEATURES" ]] && feat=(--features "$FEATURES")
  if [[ -n "$TARGET" ]]; then
    tgt=(--target "$TARGET"); outdir="$CARGO_TARGET_DIR/$TARGET/release"; out="$CAELZA_BIN-$TARGET"
  fi
  [[ "$MODE" == none ]] || prepare_target
  cd "$WORK"
  case "$MODE" in
    check)
      log "cargo check --locked -p $CAELZA_BIN ${tgt[*]:-}"
      cargo check --locked -p "$CAELZA_BIN" ${tgt[@]+"${tgt[@]}"} ${jobs[@]+"${jobs[@]}"} ${feat[@]+"${feat[@]}"}
      ;;
    build)
      log "cargo build --release --locked -p $CAELZA_BIN ${tgt[*]:-}"
      cargo build --release --locked -p "$CAELZA_BIN" ${tgt[@]+"${tgt[@]}"} ${jobs[@]+"${jobs[@]}"} ${feat[@]+"${feat[@]}"}
      mkdir -p "$DIST"
      cp "$outdir/$CAELZA_BIN" "$DIST/$out"
      log "binary → $DIST/$out"
      if [[ -z "$TARGET" ]]; then
        "$DIST/$out" --version || true
      else
        command -v file >/dev/null && file "$DIST/$out" || true
      fi
      ;;
    none) log "skipping compile (--no-build)" ;;
  esac
}

fetch_upstream
stage
rename_paths
rename_contents
apply_theme
apply_overlay
apply_assets
apply_patches
write_notice
check_residual
build
log "done: rebranded tree at $WORK"
