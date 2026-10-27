# Forge: the agent improves its own engine without holding the compiler

Vision §3.5. The Runtime (the `caelza` binary) is built by CI from this repo.
The agent cannot build it, and should not: a phone has no Rust toolchain and
an agent with a compiler and a `main` branch is an agent one bad night away
from a brick. Forge is the loop that lets it change its engine anyway:

```
agent ──propose──▶ draft PR on forge/<topic> ──CI──▶ human reviews, merges
   ▲                                                        │
   │                                                   git tag v*
   │                                                        │
   └── forge-release ◀── release.published ◀── release.yml builds caelza-<ver>-<target>.tar.gz
         (owner approves)  │
                           └──▶ body__runtime_update ──▶ the guard: fetch, verify, probe, install,
                                                         the supervisor restarts the Runtime,
                                                         last-good kept, rollback on a crash loop
```

Every arrow the agent drives goes through one tool, `git_forge`, over the
Runtime's **git channel** (upstream's `channel-git`), which authenticates as a
GitHub App installed on the repo. The agent never holds a git credential, a
clone or a compiler; the App's installation token lives in the Runtime and is
scoped to what the App was granted.

## 1. What is already there

The Runtime ships (when built with `channel-git`, see §4):

- **The git channel** (`[channels.git.<alias>]`): polls the repo's REST API
  (no webhook, no public URL), converses on issues and PRs when @mentioned,
  and routes repository events (`pull_request.merged`, `workflow_run.failed`,
  `release.published`, …) to the agent as messages or to a procedure.
- **`git_forge`**: one tool for every forge operation, as a `{resource,
  action}` grid (`pull.create`, `pull.list`, `comment.create`, `review.list`,
  `issue.*`, `label.*`, …) plus `raw` for any REST path under the API base
  (`GET repos/{r}/contents/{path}`, `POST repos/{r}/git/refs`, `PUT
  repos/{r}/contents/{path}`, `GET repos/{r}/releases/tags/{tag}`, …).
  `action: "describe"` prints the grid.
- **Channel-triggered procedures**: a `SOP.toml` trigger of `type =
  "channel"`, `channel = "git"`, `alias = "<alias>"` with a `condition` on
  `$.event_type` starts a run from a routed event.

What this repo adds is the two procedures, the wiring, the release build with
the channel in, and the two Body tools that close the loop on the machine
that runs the Runtime.

## 2. The GitHub App

One-time, on github.com. Settings → Developer settings → GitHub Apps → New
GitHub App (under the organisation that owns the repo).

1. **Name** anything (the agent comments as `<name>[bot]`), **Homepage URL**
   anything; **Webhook → Active: off** (the channel polls).
2. **Repository permissions**, exactly these:
   - Contents: **Read and write** (the proposals are commits; upstream's
     conversational channel needs only read)
   - Pull requests: **Read and write**
   - Issues: **Read and write**
   - Metadata: Read-only (automatic)
   - Actions: **Read-only** (the `workflow_run.*` events)
3. Create it, note the **App ID**, generate a **private key** (`.pem`).
4. **Install App** → the organisation → *Only select repositories* →
   `Enlightened-Republic/Caelza`.

Put the key into the Runtime's encrypted store on the phone or hub:

```sh
caelza config set channels.git.forge.private_key     # paste the PEM, BEGIN/END lines included
```

(or keep the `.pem` at a path only you can read, mode 600, and set
`private_key_path`).

## 3. The config

[`runtime/caelza.forge.example.toml`](../runtime/caelza.forge.example.toml) is
the block to merge into `~/.caelza/config.toml` beside the phone or hub
example: the channel (`app_id`, `repos`, polling every 60 s, `mention_only`),
the **events table** that starts `forge-release` on `release.published` and
delivers CI failures, merges and review comments as messages, the **peer
group** naming the GitHub logins allowed to talk to the agent on the repo,
`git.forge` added to the agent's channels, and the gates to add to the risk
profile: `git_forge` and `body__runtime_update` in `always_ask`,
`body__runtime_status` in `auto_approve`.

Then `caelza daemon`; `caelza channel list` shows Git as compiled and
configured, and the daemon log shows the channel minting its App token and
resolving its bot login.

## 4. The build flag

Upstream keeps `channel-git` out of the lean default feature set, so a plain
`cargo build -p caelza` answers `caelza channel list` with "Git (configured,
not compiled)". This repo's release workflow
([`.github/workflows/release.yml`](../.github/workflows/release.yml)) builds
every archive with `--features channel-git`, and `runtime/build.sh` passes
the same flag by default (`CAELZA_FEATURES=` to drop it), so the gate
compiles what the release ships.

## 5. The procedures

Both live in [`body/sops`](../body/sops) with the phone playbooks and are
installed by `caelza-body playbooks --install` (and `install.sh`). Both are
owned by `agents.main`, run in `auto` mode with one gate each, and admit one
run at a time.

### `forge-propose` (manual)

1. **Frame the change**: what, why, which files; inside the allowed surface
   (below); `pull.list` to avoid a second PR on a topic that has one.
2. **Read what is there and draft**: `raw GET repos/{r}/contents/{path}?ref=main`
   per file (content and the `sha` the write needs), main's sha; the full
   new content of every file, a commit message each, the PR title and body
   (what, why, how CI proves it, how it is undone). The owner sees the plan.
3. **Propose** (gate): create `forge/<slug>` from main, `PUT` each file on
   the branch, `pull.create` as a **draft**. Never `main`, never another
   branch, one PR per run.
4. **Report**: the URL, what happens next, where CI results and review
   comments will arrive (the PR thread, through the channel).

The surface the agent may change: `runtime/overlay/**`, `runtime/patches/**`,
`runtime/*.example.toml`, `body/sops/**`, `guide/**`, `docs/**`,
`caelza_body/agent/**`, `mind/**`, `brand/**`. Never `.github/workflows/**`,
`install.sh`, `runtime/termux-install.sh`, `runtime/build.sh`,
`caelza_body/supervisor.py`, `caelza_body/runtime_guard.py` (the guard that
will install what it proposes). The procedure's text binds the model; CI
(the Body tests, the Runtime gate), branch protection on `main` and a human
reviewer bind the repo.

### `forge-release` (on `release.published`, or by hand with `{"tag": "v0.1.1"}`)

1. **Read the release**: `body__runtime_status` (versions, this machine's
   target), `raw GET repos/{r}/releases/tags/{tag}` for the assets; stop if
   the archive for this target is missing (the Android leg is experimental).
   Tell the owner what changed and that the Runtime will restart if the new
   binary holds.
2. **Update** (gate): `body__runtime_update(tag, reason)`, once.
3. **Confirm**: `body__runtime_status` until the update is done; the result
   from its log tail; `caelza-body runtime rollback` undoes it by hand.

## 6. The two Body tools

`caelza-body serve` grew a `runtime` group (the machine that runs the
Runtime; a phone that only runs a Body in a hub fleet has no Runtime to
update):

| tool | class | does |
|---|---|---|
| `runtime_status` | read-only | `caelza-body runtime status` plus whether an update is running and the tail of its log |
| `runtime_update(reason, tag?)` | destructive, `always_ask` | starts `caelza-body runtime update [--tag]` **detached**, logs to `~/.caelza-body/logs/runtime-update.log`, audits the reason; returns at once (the call's own Runtime is the one that restarts at the end) |

The guard itself is unchanged: fetch, verify the `.sha256`, unpack and probe
in the work dir on a copy of the config, install, move `current`, keep
`last-good` on the version that was running, ask the supervisor to restart;
the supervisor promotes the new version to `last-good` after ten minutes and
rolls back on a crash loop ([`body/README.md`](../body/README.md), "The
Runtime under the guard").

## 7. Safety and limits

- **Two gates on every write**: the procedure's `requires_confirmation` step,
  and `git_forge` in the risk profile's `always_ask` (every call, reads
  included; an owner who trusts the procedure's gate can leave the tool to
  the profile's normal policy instead). `body__runtime_update` always asks.
- **The App's permissions are the ceiling**: no admin, no workflows, no
  secrets. A merge is a human's click; a release is a human's tag.
- **Rate budget**: an installation gets 5,000 requests an hour; the
  conversational default spends 2 per repo per tick, each routed event
  family 1 more. At 60 s, one repo, four routed events: about 360 an hour.
- **A failed CI run on a forge PR** reaches the agent as a message on the
  PR; it may answer on the thread and, if the fix is clear, run
  `forge-propose` again on the same branch (the `PUT` with the file's new
  `sha` is a second commit; the PR follows the branch).
- **Gitea / Forgejo** work the same way with `provider = "gitea"`,
  `api_base_url` and an `access_token` instead of the App.
- **Without the channel** (a Runtime built without `channel-git`), the
  procedures validate but `git_forge` answers that no git channel is
  configured; `caelza-body runtime update` by hand still pulls a release.
