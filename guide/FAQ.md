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

## What does the Cael button in the top bar do?

Cael's face sits in the top bar of every dashboard page. Tap it and a panel
says what the screen you are on is for and what the next step is, in his
words, with no model needed. Below that you can ask him anything about the
screen; the answer streams from the Cael agent on the local model, and his
look talks while he answers. Escape or the X closes the panel. If Cael is not
set up as an agent yet, the panel still explains the screen and points at the
setup.

## What are looks?

Every agent has a look: a small pixel character, one piece per layer
(backdrop, body, outfit, hair, hat, face, accessory) in the colours you choose
(skin, hair, outfit, accent, eyes). It blinks on its own and talks in the chat
while the agent answers; it stands beside the agent's messages, on its chat
tab, in the agents list and on Home. A new agent is dealt a look from its
name; Cael's is fixed (the constellation hoodie and galaxy eyes). A look is
saved on the Runtime under `~/.caelza/agents/<alias>/look.json`, so every
device shows the same character.

## How do I dress an agent?

Open Looks in the dashboard's menu (`/looks`) and tap the agent, or go
straight to `/looks/<alias>`. Pick a tab per layer, tap a piece, tap a colour
per slot (or choose any colour), watch the preview, then Save look. Undo puts
the saved look back; Back to the default drops the saved look. A dimmed piece
comes with a pack that is not in your wardrobe yet.

## What is the Shop, and what is a pack?

The Shop (`/shop`) sells packs of pieces for the looks. Starter is always
yours; Cosmic (Cael's own pieces) is free and joins your wardrobe with one
tap; Arcade is the first priced pack and opens with an unlock code. The
wardrobe is the list of packs you added, kept on the Runtime at
`~/.caelza/looks/wardrobe.json`, so it is the same on the phone and the
desktop. Removing a pack from the wardrobe deletes nothing: add it back any
time, and a pack you unlocked once needs no code again.

## What is an unlock code?

A code opens a priced pack. It looks like `ARCADE-7K3PQ2M9-` followed by a
long signature, it comes with your purchase, and you paste it into the box
under the pack in the Shop and tap Unlock. The Runtime checks the signature
itself, offline, against the shop's public key; nothing is sent anywhere. A
code that is mistyped or meant for another pack says so. Codes are cosmetic:
they open pieces for the looks and nothing else.

## How do I use my agent's look as a profile picture?

On the agent's customizer (`/looks/<alias>`) tap Save as avatar: a 512 × 512
PNG named `<alias>-avatar.png` lands in your downloads, with Space behind a
look that has no backdrop. Telegram, Discord and the rest take it as is. From
the command line, `python3 scripts/looks.py avatar <alias> out.png` writes the
same file.

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
screen. The Caelza app on a phone pairs its own dashboard shell by itself, so
no code is typed there, and no other app on the phone can use its gateway.

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
check. On a phone the app runs it; on a Linux hub `mind/install.sh` installs
it; on a Windows PC `mind/windows-install.ps1` does, and the Start menu's
Caelza starts it with the Runtime.

## How do I turn on long-term memory on the PC?

On the dashboard's Memory page, tap **Turn on memory**. Caelza sets the
Mind up on that PC itself: it downloads the Mind and a small Node runtime
it runs on (about 60 MB, once; each file checked against its published
sum), installs it under your user folder (`%LOCALAPPDATA%\Caelza\mind` on
Windows, `~/.local/share/caelza/mind` elsewhere), makes the agent's keys,
starts the Mind and sets it to start with the PC. Then tap **Reload
daemon** in the yellow bar at the top so the agent's next turn uses it.
No account, and nothing leaves the PC. If something fails, the card shows
the last lines of what happened and a **Try again** button. The PowerShell
one-liner (`mind/windows-install.ps1`) and `mind/install.sh` do the same
thing and can still be used instead; they share the directories. The phone
app does not install a Mind of its own; it joins the PC's.

## Can Cael remember on my PC and my phone?

Yes: one Mind can serve both, so what Cael learns on one device he knows on
the other. On the device that runs the Mind (usually the PC), open the
dashboard's Memory page, find **Your other devices** and tap **Share on
Home network** (or **Share on Tailscale** when you have it). The page shows
a join code; copy it. If it says to, restart the Mind once (on Windows close
the Caelza Mind window and open Caelza from the Start menu again), and say
yes if Windows asks whether Node.js may use your private network. On the
other device, open its Memory page, paste the code under **Join a Mind on
another device** and tap **Join**. The page shows the shared brain straight
away; for the agent's next turn to use it, tap **Reload daemon** in the
yellow bar at the top of the dashboard, or restart Caelza once (Stop, then
Start on the phone). Both devices have to be on the same Wi-Fi or both on
Tailscale. The Mind listens on that address besides its own 127.0.0.1, never
on the open internet, and a code that points at an internet address is
refused. On home Wi-Fi the link is not encrypted, so share only on a network
you trust; Tailscale encrypts it. Every code is new, devices already joined
keep theirs, and **Stop sharing** cancels every code at once (the address
closes when the Mind next restarts; without a code nothing can use it). **Use
this device's own memory** on the joined device undoes the join.

## What are procedures?

Procedures are step-by-step playbooks the agent runs with a gate before the
step that changes the phone: debloat a carrier phone, remove malware, set up a
new phone, run diagnostics. Start one from the dashboard's Procedures page,
pick the phone, and approve or deny at the gate. The deterministic parts (the
debloat plan, the suspects list, the health check) are read-only tools you can
run on their own.

## How do I connect my apps (Gmail, Calendar, Drive, Notion, Slack)?

Through Maton, a service that keeps the sign-in to each app so Caelza does not
have to. Make a free account at maton.ai, connect the apps you want there, and
copy your Maton API key from its settings. Then open the dashboard's Connect
page, paste the key into the "Your apps" card and press Connect: Cael adds
Maton's server to the Runtime, keeps the key encrypted, and grants it to your
main agent. (The shell way is `sh scripts/maton-connect.sh`, which asks for the
key at a masked prompt.) Caelza picks it up the next time it starts; then ask
something harmless first, such as what is on your calendar today. The key is
never shown again; anyone who holds it can reach every app you connected, so
treat it like a password. Reading is free; sending, posting, paying and
deleting always ask you first.

## How do I connect my smart home (Home Assistant)?

Caelza talks to your lights, switches and thermostats through Home Assistant,
which must be version 2025.2 or newer and on the same Wi-Fi as the device
running Caelza. In Home Assistant: Settings > System > AI, turn the Model
Context Protocol Server on; expose the devices Caelza may use to voice
assistants (Settings > Voice assistants > Expose); then create a long-lived
access token (your profile > Security). Caelza only sees what you exposed.
Then open the dashboard's Connect page: the "Smart home" card takes Home
Assistant's address (http://homeassistant.local:8123 unless yours differs) and
the token, and Connect does the rest. (The shell way is `sh
scripts/home-connect.sh http://your-address:8123`, which asks for the token at
a masked prompt.) Reading what is on is free; anything that acts on the house
asks you first, and locks, doors and alarms always ask. This is new and has not
been tried against a real Home Assistant yet, so tell us if the token is
refused.

## Can Caelza watch my 3D printer?

Yes, for printers running Moonraker (Klipper, Mainsail, Fluidd) or OctoPrint, as
long as the printer is on the same Wi-Fi as the device running Caelza. Bambu Lab
printers are not supported yet. Caelza can tell you the state, progress, time left
and temperatures, and fetch a camera snapshot. It can pause or cancel a print only
after you say yes; it never starts prints, sends G-code or hits the emergency stop.
To set it up, open the dashboard's Connect page: the "3D printer" card takes the
printer's address (that one address is allowed, not your whole network), which
software it runs, and for OctoPrint its API key (kept as a secret); Connect
writes the config and installs the printer skill for your main agent. (By hand:
`runtime/caelza.printer.example.toml` and the skill in the `skills` folder.)
Every request asks you for approval, reads included. This is new and has not
been tried against a real printer yet.

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

## Can I use Caelza on a Windows PC?

Experimentally. The Runtime has a Windows build (64-bit Windows 10 or 11) that
is new and has not been through real use yet. In PowerShell, run
`irm https://raw.githubusercontent.com/Enlightened-Republic/Caelza/main/runtime/windows-install.ps1 | iex`
(`runtime/windows-install.ps1`). It checks the download, installs to
`%LOCALAPPDATA%\Caelza`, and puts `caelza` on your PATH. Then run `caelza
daemon` and open `http://127.0.0.1:42617` for Cael's setup (`Caelza-Setup.exe`
on the same release does all of this with a Start menu entry). Settings live in
`.caelza` in your user folder. If a release has no Windows build, the installer
says so. The Mind (long-term memory) is one tap on the Memory page (**Turn
on memory**; nothing to install first); the PowerShell one-liner
`mind/windows-install.ps1` (needs Node.js 22) does the same. Either way the
Start menu's Caelza then starts both. The Android app is phone-only, and the Body works with a
phone over ADB rather than on the PC itself. WSL2 with the Linux build is the
fallback.

## Cael says he can't see Ollama. What is it, and what do I do?

Ollama is the free program that runs the local model on a computer (a phone
uses llama.cpp inside the app instead). On a PC the "free and local" door
needs it: Cael's setup page asks Ollama on the same computer what it has
(`http://127.0.0.1:11434`), and when nothing answers he shows a **Get Ollama**
link to `https://ollama.com/download`. Install it, leave it running (it sits in
the tray), and press **Check again**. Once it answers, the button becomes
**Download N GB and use this**: Cael pulls the model the ladder picked for your
memory (and his own 1.5B when it differs) with a progress bar, then sets the
agent up as "Use this" would. Only a page open on the computer itself can do
this; from another device Cael says so and gives the `ollama pull` line to run
there. The download can be stopped and picks up where it left off next time.
