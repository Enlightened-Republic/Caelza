#!/usr/bin/env bash
# Caelza Mind — pack xanima-server, the brain service, as a release asset.
#
#   ./mind/pack.sh --version 0.2.0 --out dist/mind                    # fetch the pinned commit, build, pack
#   ./mind/pack.sh --checkout ~/xanima --version dev --out /tmp/mind  # from a checkout you already have
#
# Writes <out>/caelza-mind-<version>.tgz and its .sha256: `npm pack` of the
# xanima-server workspace after a build (dist/cli.js with xanima-core and the
# MCP SDK inlined; the two native sqlite modules stay its runtime dependencies
# and are installed where the tarball lands, see install.sh). The commit is
# bundle/manifest.toml's [components.mind] service_commit unless --commit says
# otherwise; a checkout handed in must sit on that commit. release.yml runs
# this for every tag; nothing generated is committed.
#
# Env: CAELZA_MIND_TOKEN   a token with read access to the xanima repo, needed only
#                          while that repo is private (release.yml passes the repo's
#                          XANIMA_READ_TOKEN secret); CAELZA_MIND_REPO overrides the repo
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
REPO="${CAELZA_MIND_REPO:-https://github.com/Enlightened-Republic/xanima}"

say() { printf '\033[1;36m[caelza-mind]\033[0m %s\n' "$*"; }
die() { printf '\033[1;31m[caelza-mind] error:\033[0m %s\n' "$*" >&2; exit 1; }
need() { command -v "$1" >/dev/null 2>&1 || die "$1 is required"; }

commit="" version="" out="" checkout=""
while [ $# -gt 0 ]; do
  case "$1" in
    --commit) commit="$2"; shift 2 ;;
    --version) version="$2"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    --checkout) checkout="$2"; shift 2 ;;
    -h|--help) sed -n '2,17p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown argument: $1 (see --help)" ;;
  esac
done
[ -n "$version" ] || die "--version is required: the Caelza version the asset is named for (0.2.0, or dev-<sha>)"
[ -n "$out" ] || die "--out is required"
case "$version" in */*|*' '*|'') die "--version must be one word without a slash" ;; esac

if [ -z "$commit" ]; then
  commit="$(sed -n -E 's/^service_commit[[:space:]]*=[[:space:]]*"([0-9a-f]{40})".*/\1/p' "$ROOT/bundle/manifest.toml")"
  [ -n "$commit" ] || die "bundle/manifest.toml names no [components.mind] service_commit"
fi

need git; need node; need npm; need tar; need sha256sum
node -e 'const [m] = process.versions.node.split(".").map(Number); process.exit(m >= 22 ? 0 : 1)' \
  || die "node $(node --version) is too old; xanima-server needs node >= 22"

mkdir -p "$out"
out="$(cd "$out" && pwd)"

work=""
if [ -z "$checkout" ]; then
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  checkout="$work/xanima"
  say "fetching $REPO at $commit"
  # The token, when there is one, travels as a header for this one command, never in
  # the remote URL (which git would keep in .git/config and print in its errors). Only
  # CAELZA_MIND_TOKEN: the workflow's own GITHUB_TOKEN cannot read another repo, and a
  # wrong Authorization header turns even a public fetch into a 401.
  auth=()
  if [ -n "${CAELZA_MIND_TOKEN:-}" ]; then
    auth=(-c "http.extraheader=Authorization: Basic $(printf 'x-access-token:%s' "$CAELZA_MIND_TOKEN" | base64 | tr -d '\n')")
  fi
  git init -q "$checkout"
  git -C "$checkout" remote add origin "$REPO"
  git ${auth[@]+"${auth[@]}"} -C "$checkout" fetch -q --depth 1 origin "$commit" \
    || die "could not fetch $commit from $REPO. A private repo needs CAELZA_MIND_TOKEN, a token with read access to it (in CI: the XANIMA_READ_TOKEN secret); a wrong commit needs the manifest's service_commit fixed"
  git -C "$checkout" checkout -q --detach FETCH_HEAD
fi
head="$(git -C "$checkout" rev-parse HEAD)"
[ "$head" = "$commit" ] || die "$checkout is at $head, not the pinned $commit (git checkout $commit there, or pass --commit $head)"
[ -f "$checkout/packages/server/package.json" ] || die "$checkout has no packages/server: not the xanima monorepo"

say "npm ci"
(cd "$checkout" && npm ci --no-audit --no-fund --loglevel=error)
say "building xanima-core, xanima and xanima-server"
(cd "$checkout" && npm run build >/dev/null)
[ -f "$checkout/packages/server/dist/cli.js" ] || die "the build left no packages/server/dist/cli.js"

service_version="$(node -p 'require(process.argv[1]).version' "$checkout/packages/server/package.json")"
built="$(node "$checkout/packages/server/dist/cli.js" --help 2>/dev/null | head -1 || true)"
say "built: ${built:-xanima-server $service_version}"

say "packing the xanima-server workspace"
packed="$(cd "$checkout" && npm pack --workspace xanima-server --pack-destination "$out" --json 2>/dev/null \
  | node -e 'let s = ""; process.stdin.on("data", d => s += d).on("end", () => { const [p] = JSON.parse(s); process.stdout.write(p.filename); })')"
[ -n "$packed" ] && [ -f "$out/$packed" ] || die "npm pack wrote nothing"
# (grep without -q: it reads the whole listing, so tar never dies of SIGPIPE under pipefail)
tar -tzf "$out/$packed" | grep -x 'package/dist/cli.js' >/dev/null || die "$packed has no package/dist/cli.js"

name="caelza-mind-$version.tgz"
mv -f "$out/$packed" "$out/$name"
(cd "$out" && sha256sum "$name" > "$name.sha256")
say "wrote $out/$name (xanima-server $service_version at ${head:0:10}) and $name.sha256"
