# Caelza FAQ

Plain answers to the questions a new owner asks. Cael, the guide, reads these
(they are part of his corpus, `guide/corpus.jsonl`) and answers in his own
voice; the facts here must stay true, so `tests/test_cael_corpus.py` checks
the ports, paths and names against the rest of the repo.

## What is Caelza?

Caelza is an agent that lives on your own hardware. It is three layers: the
Runtime (the engine: the agent loop, model providers, channels, tools, the
dashboard), the Mind (long-term memory that forgets what stops mattering) and
the Body (the phone's sensors and device tools). It runs on a phone, a laptop
or a small server, and the dashboard is at http://127.0.0.1:42617 on that
device unless you moved it.

## Do I need an account or an API key?

No. Caelza works with no account and no API key: a free local model, DeepSeek
R1, runs on your device and is the agent's default brain. A provider key is
the other door: it gives the agent a bigger brain in the cloud. You can add
one later at any time.

## What is an API key?

An API key is a password for a model provider such as Anthropic, OpenAI or
OpenRouter. It lets Caelza send the agent's requests to that provider under
your account. Caelza keeps the key encrypted on this device and only ever
sends it to that provider. A key is set with `caelza config set`, for example
`caelza config set providers.models.anthropic.default.api_key`, which prompts
for the value, and never typed into a chat.

## What is a provider, and what is an alias?

A provider is who runs the model: Anthropic, OpenAI, OpenRouter, MiniMax,
Ollama, llama.cpp, any OpenAI-compatible endpoint. An alias is one configured
entry under a provider, named `<provider>.<alias>`: `llamacpp.local` is the
local model on a phone, `ollama.local` the local model on a hub,
`anthropic.default` a key you added. An agent points at one alias with
`agents.<name>.model_provider`; the owner's agent is `agents.main`.

## How do I switch the agent to a cloud model?

Add the provider's key, then point the agent at it:

```sh
caelza config set providers.models.anthropic.default.api_key
caelza config set providers.models.anthropic.default.model claude-sonnet-4-5
caelza config set agents.main.model_provider anthropic.default
```

The dashboard's Quickstart does the same through its "Bring your own key"
door. Cael keeps running on the local model either way.

## Which local model do I get?

The ladder is honest about size. A hub with 16 GB of RAM or more runs
`deepseek-r1:14b` on Ollama; 8 to 12 GB runs `8b`. A phone with 6 GB or more
runs `DeepSeek-R1-Distill-Qwen-7B` (Q4) on llama.cpp; a phone with 5 GB or
less runs the 1.5B, which is good for chat and explanations and not reliable
for long tool-using jobs. Cael always runs on the 1.5B. On a phone the model
server listens on 127.0.0.1:8080; the models live under `~/.caelza/models`
(the app keeps them under its own files directory).

## Who is Cael?

Cael is the guide inside Caelza: he explains screens, settings, errors and
approvals in plain language, offline, with no account. He runs on the local
model, has no tools and cannot change settings or act for you; he points at
the next step. The agent is yours; Cael is the manual that talks. His persona
lives in `~/.caelza/agents/cael/workspace/SOUL.md`.

## What is an approval, and what happens if I deny it?

An approval is the owner's safety gate. When the agent wants to do something
its risk profile does not auto-approve (uninstall an app, delete a file, send
money, anything hard to undo), it stops and asks. Approving runs the action;
denying stops it and tells the agent why. Either answer is fine. Before any
package is removed, the Body snapshots the package list so the removal can be
undone. Pending approvals show on the dashboard's Home page under "waiting on
you".

## What is a risk profile?

A risk profile says which tools an agent may use and which actions need an
approval. The `phone` profile auto-approves reads (battery, notifications,
the package list) and asks before anything irreversible. Cael's profile,
`guide`, is read-only with every tool denied. Profiles live under
`[risk_profiles.<name>]` in `~/.caelza/config.toml`.

## What is Shizuku, and why does it keep asking?

Shizuku gives the Caelza app shell-level control of this phone without
root: the device tools (packages, settings, screen capture, input) run
through it. It has to be started again after every reboot unless the phone is
rooted: open Shizuku and tap Start. Without it, the sensors still work and
the device tools answer "needs Shizuku". On a Termux install the same role is
played by wireless debugging (ADB) on the phone itself, set up by
`python scripts/setup.py`.

## How do I pair the dashboard?

The first browser or app to open the dashboard must pair. The gateway prints a
pairing code in its log; `caelza gateway get-paircode` prints it again and
`caelza gateway get-paircode --new` makes a fresh one. Type it on the pairing
screen. The Caelza app on a phone runs its own gateway with pairing off, so
its dashboard opens without a code.

## How do I pair another phone?

On the Bodies page of the dashboard (or with the agent's `device_pair` tool):
turn on Wireless debugging on the other phone, read its pairing code and
address, and enter them. The agent can then read that phone and, with
approvals, change it. A phone running its own Body can instead be joined over
the network with `caelza-body fleet join` (or the agent's `device_join`), with
its token kept in a file, never in the chat.

## What is the Body?

The Body is the device layer: sensors (camera, microphone, location,
notifications, battery, clipboard, text-to-speech, torch) and device tools
(packages, settings, screen capture, input, logs) on this phone and on paired
phones. Every dangerous action needs a reason, is written to an audit log
(`~/.caelza-body/logs/device-actions.log`), and a package list is snapshotted
before anything is removed. The Body is served to the Runtime as an MCP server
on 127.0.0.1:42618 behind a token file.

## What is the Mind?

The Mind is Caelza's long-term memory, built on xanima: it remembers across
sessions, keeps what matters and forgets what stops mattering, and sleeps to
consolidate. Ask the agent what it remembers, or tell it to forget something.
The dashboard's Memory page shows the brains, what is waiting for review, and
lets you recall or forget by hand. `caelza memory stats` is the command-line
check.

## What are procedures?

Procedures are step-by-step playbooks the agent runs with a gate before the
step that changes the phone: debloat a carrier phone, remove malware, set up a
new phone, run diagnostics. Start one from the dashboard's Procedures page,
pick the phone, and approve or deny at the gate. The deterministic parts (the
debloat plan, the suspects list, the health check) are read-only tools you can
run on their own.

## Where do settings live?

The Runtime's config is `~/.caelza/config.toml` (the app keeps it under its
own files directory). Change it with `caelza config set <path> <value>` so the
Runtime validates every value and encrypts secrets; the dashboard's Config
page does the same. The Body's own settings are in `~/.caelza-body/config.toml`.

## How is the Runtime updated?

Through the guard: `caelza-body runtime update` finds the release, verifies
its checksum, probes the new binary (`caelza --version` must answer with the
release's version and the gateway must serve `/health`), keeps the previous
version as `last-good`, and rolls back on a crash loop. The Caelza app does
the same by itself. Nothing is trusted before it is probed.

## Where do I see what went wrong?

The dashboard's Logs page shows the Runtime's log; the Home page shows
whether the Runtime, the Mind and the Body are up. On a phone with the app,
the status strip under the dashboard says what each layer is doing and what it
needs (Shizuku, a permission, a model still downloading). `caelza daemon`
prints its log to the terminal on a Termux install.

## How do I install it?

On a phone, the Caelza app: it installs the Runtime, runs the first setup with
Cael, and serves the Body itself. In Termux, one line installs the Runtime
(`runtime/termux-install.sh`) and one line installs the Body (`install.sh`);
`scripts/model-setup.sh` fetches the free model and creates Cael. On a laptop
or server, build the Runtime with `./runtime/build.sh`, run `caelza
quickstart`, then `caelza daemon`.
