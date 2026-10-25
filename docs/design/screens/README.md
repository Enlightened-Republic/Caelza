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
| `procedures.png` | Procedures: waiting, running, the library, finished |
| `dashboard.png` | the upstream dashboard at `/dashboard`, its tab bar scrolling |
| `agent-chat.png` | the chat with its toolbar wrapped onto two rows |
| `tools.png` | Tools, its controls wrapped and the CLI table scrolling inside its card |
| `runs.png` | SOP Runs with its page padding and a header title |
| `drawer.png` | the mobile menu: Home, Bodies, Memory, Procedures first |

The Mind and Body content in these shots comes from the tool's mock proxy
(canned `brain_stats`, `brain_status`, `device_list`, sensor readings), the
rest from a real gateway with the SOP engine off.
