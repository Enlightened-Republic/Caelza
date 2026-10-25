# Dashboard screens

Reference screenshots of the Caelza dashboard, taken with
`runtime/tools/phone-shots` against a running gateway. They document the
phone-first pass (vision §7, M4 phase 3b) and are the baseline the next pass
compares against; regenerate them with the same tool when a page changes.

## `390/` — phone width, 390 × 844, 1× scale, dark

| file | what it shows |
|---|---|
| `home.png` | Home: the Runtime / Mind / Body tiles, waiting on you, the digest |
| `bodies.png` | Bodies: this phone and the paired phones, senses, capture, packages |
| `memory.png` | Memory: the brains, status, recall, the review queue |
| `procedures.png` | Procedures: waiting, running, the library with the four phone playbooks (M5), finished |
| `procedures-run.png` | the Run dialog for `phone-debloat`: which phone, what to leave alone, where the gate is |
| `dashboard.png` | the upstream dashboard at `/dashboard`, its tab bar scrolling |
| `agent-chat.png` | the chat with its toolbar wrapped onto two rows |
| `tools.png` | Tools, its controls wrapped and the CLI table scrolling inside its card |
| `runs.png` | SOP Runs with its page padding and a header title |
| `drawer.png` | the mobile menu: Home, Bodies, Memory, Procedures first |

The Mind and Body content in these shots comes from the tool's mock proxy
(canned `brain_stats`, `brain_status`, `device_list`, sensor readings), the
rest from a real gateway. The Procedures shots (M5) have the playbooks
installed under the gateway's `shared/sops`; the gateway runs standalone
(`caelza gateway start`), so the page says the engine is not running in this
process, which is what a standalone gateway is.
