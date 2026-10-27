# Forge: a release is out

The last step of the Forge loop. A merged pull request becomes a Runtime
when a `v*` tag is pushed: CI builds `caelza-<version>-<target>.tar.gz` for
each target and publishes the release. The git channel delivers the
`release.published` event here; this procedure reads it, tells the owner
what changed and whether this machine's archive is in the release, and after
the owner's approval starts the guard (`body__runtime_update`), which
downloads, verifies, probes and installs the binary and asks the supervisor
to restart the Runtime on it. A binary that does not hold is discarded and
nothing changes.

The trigger payload is the release event (`tag`, `name`, `body`, `html_url`,
`repo`) or, from a manual start, `{"tag": "v0.1.1"}`; with no `tag` at all,
the latest release.

## Safety

The guard never trusts a binary it has not probed: `caelza --version` must
answer with the release's version and `caelza gateway start` must serve
`/health` on a copy of the config before anything is installed. The
supervisor keeps `last-good` on the version that was running and rolls back
to it on a crash loop. The Update step parks the run until the owner approves
it, and `body__runtime_update` is in the risk profile's `always_ask`, so the
owner is asked twice; the update also ends the current Runtime's
conversations when the new binary takes over, which the owner is told
before approving.

## Steps

1. **Read the release** — Take the `tag` from the trigger payload (empty means
   the latest). Call `body__runtime_status` for the versions installed, the
   current one and this machine's `target`. Call `git_forge` with `action:
   "raw", method: "GET", path: "repos/<repo>/releases/tags/<tag>"` (or
   `repos/<repo>/releases/latest`) and read its `assets`: the release must
   carry `caelza-<version>-<target>.tar.gz` and its `.sha256` for this
   machine's target; the Android build is experimental and may be missing,
   in which case say so and stop. Tell the owner, in plain words: the
   version, what the release notes say changed, that the current version is
   X, that the update downloads and probes the new binary first, that the
   Runtime restarts if it holds (ending this conversation for a minute), and
   that a binary that does not hold changes nothing. No changes in this step.
   - tools: body__runtime_status, git_forge
   - allow-tools: body__runtime_status, git_forge

2. **Update** — Approval of this step is the owner's go-ahead for this release.
   Call `body__runtime_update(tag, reason)` once, the reason naming the tag
   and who asked. It returns at once with the log path; the guard runs on its
   own. Do not call it twice, and do not call anything else in this step.
   - tools: body__runtime_update
   - allow-tools: body__runtime_update, body__runtime_status
   - requires_confirmation: true

3. **Confirm** — Call `body__runtime_status` until `update_running` is empty
   (a few minutes at most; wait between calls). Report the outcome from its
   log tail: the new version installed and current with a restart requested
   (the supervisor restarts the Runtime, which may end this run before the
   report is sent, so keep it short), or the probe's failure and that
   everything stayed as it was. Say which version is `last-good` now and
   that `caelza-body runtime rollback` undoes the swap by hand.
   - tools: body__runtime_status
   - allow-tools: body__runtime_status
