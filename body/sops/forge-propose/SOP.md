# Forge: propose a Runtime change

The agent improves its own engine without ever holding the compiler. A change
to the Runtime is a pull request to the Caelza repo: this procedure frames
it, drafts it, and after the owner's approval writes it to a `forge/<topic>`
branch and opens a draft PR, all through `git_forge`, the Runtime's forge
tool over the git channel (a GitHub App installed on the repo). CI builds and
tests it, a human reviews and merges it, a `v*` tag releases it, and the
guard (`forge-release`) pulls the release onto this machine.

The trigger payload may carry `topic` (a few words), `why` (what is wrong or
missing), `files` (paths the change touches, if known) and `repo` (default
`Enlightened-Republic/Caelza`). A chat start gets them from the conversation.

## Safety

Two gates stand in front of every write: this procedure parks at the Propose
step until the owner approves the drafted PR as written, and the risk
profile asks on each `git_forge` call (`runtime/caelza.forge.example.toml`).
The surface the agent may change is bounded: `runtime/overlay/**`,
`runtime/patches/**`, `runtime/*.example.toml`, `body/sops/**`, `guide/**`,
`docs/**`, `caelza_body/agent/**`, `mind/**`, `brand/**`. It never touches
`.github/workflows/**`, `install.sh`, `runtime/termux-install.sh`,
`runtime/build.sh`, `caelza_body/supervisor.py` or `caelza_body/runtime_guard.py`
(the guard that will install what it proposes), and it never writes to
`main` or to a branch it did not create. One PR per run, always a draft.

## Steps

1. **Frame the change** — From the trigger payload and the conversation, write
   down in one paragraph what should change in the Runtime, why, and which
   files it touches; stay inside the surface named under Safety, and stop
   with a plain explanation if the change needs a file outside it. Call
   `git_forge` with `resource: "pull", action: "list", repo` to see the open
   pull requests; if one on a `forge/` branch already covers the topic, stop
   and point the owner at it instead of opening a second. Name the branch
   `forge/<topic-slug>` (lowercase, hyphens). No writes in this step.
   - tools: git_forge
   - allow-tools: git_forge

2. **Read what is there and draft** — For each file the change touches call
   `git_forge` with `action: "raw", method: "GET", path:
   "repos/<repo>/contents/<path>?ref=main"`: the answer carries the file
   `content` (base64) and its `sha`, which the write will need; a 404 means a
   new file. Read `repos/<repo>/git/ref/heads/main` for the sha the branch
   starts from. Draft the complete new content of every file (no partial
   edits: the forge API writes whole files), one commit message per file in
   the imperative, and the pull request: a title under 70 characters, and a
   body with four parts: what changes, why, how CI proves it (the Body tests,
   the Runtime gate, the release build), and how it is undone (the guard
   keeps the last good binary; a revert PR). Show the owner the plan in plain
   words: the files, a summary of each change, the branch and the title. No
   writes in this step.
   - tools: git_forge
   - allow-tools: git_forge

3. **Propose** — Approval of this step is the owner's go-ahead for the PR as
   drafted in the previous step, nothing more. In this order, each one call
   to `git_forge`: create the branch with `action: "raw", method: "POST",
   path: "repos/<repo>/git/refs", body: {"ref": "refs/heads/forge/<slug>",
   "sha": "<main sha>"}`; write each file with `action: "raw", method:
   "PUT", path: "repos/<repo>/contents/<path>", body: {"message": "<commit
   message>", "content": "<base64 of the new content>", "branch":
   "forge/<slug>", "sha": "<the file's sha from step 2, omitted for a new
   file>"}`; then open the pull request with `resource: "pull", action:
   "create", repo, title, head: "forge/<slug>", base: "main", draft: true,
   body`. Never push to `main`, never write outside the drafted files, never
   open a second PR; if a write fails, report it and leave the branch as it
   is for the owner to inspect.
   - tools: git_forge
   - allow-tools: git_forge
   - requires_confirmation: true

4. **Report** — Give the owner the PR's URL and number, what happens next (CI
   runs the Body tests and the Runtime gate on the branch; a human reviews
   and merges; a `v*` tag builds the release; `forge-release` offers to pull
   it), and what to watch for (a failed CI run and review comments arrive on
   the PR's thread through the git channel; answer them there). Remember the
   PR number and the topic in one plain sentence so a follow-up finds it.
