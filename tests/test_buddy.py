"""The buddy (vision M10 §10): a new agent is a someone, not a help desk.

An agent the owner makes starts as a small companion: a name, a personality,
a look it can describe and cares about, a quirk and likes, its own moods and
wants, and a first hello in character that is curious about the owner, never
"How can I help you today?". Three places say it: the Runtime's starter files
for an agent made anywhere (runtime/patches/0032-buddy.patch), the first run's
personality pick and the files it writes (lib/buddy.logic.ts, Setup.tsx), and
Cael's meeting (shape_agent.rs keeps the pick and gives every soul the same
"How I live"). The Looks page puts the look in words into IDENTITY.md, since
the Runtime reads that file into every prompt and never look.json. These pins
keep them saying the same thing and keep Cael, the guide, out of it; the
logic's behaviour is under the web suite (`buddy.logic.test.ts`), the tool's
under `cargo test -p caelza-tools -- shape_agent::`.
"""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WEB = REPO_ROOT / "runtime" / "overlay" / "web" / "src"
LOGIC = (WEB / "lib" / "buddy.logic.ts").read_text(encoding="utf-8")
LOGIC_TEST = (WEB / "lib" / "buddy.logic.test.ts").read_text(encoding="utf-8")
IDENTITY_LOGIC = (WEB / "lib" / "identity.logic.ts").read_text(encoding="utf-8")
CLIENT = (WEB / "lib" / "identity.ts").read_text(encoding="utf-8")
SETUP = (WEB / "pages" / "setup" / "Setup.tsx").read_text(encoding="utf-8")
LOOKS = (WEB / "pages" / "Looks.tsx").read_text(encoding="utf-8")
CAEL_CLIENT = (WEB / "lib" / "cael.ts").read_text(encoding="utf-8")
PATCH = (REPO_ROOT / "runtime" / "patches" / "0032-buddy.patch").read_text(encoding="utf-8")
SHAPE = (REPO_ROOT / "runtime" / "overlay" / "crates" / "caelza-tools" / "src" / "shape_agent.rs").read_text(encoding="utf-8")
FAQ = (REPO_ROOT / "guide" / "FAQ.md").read_text(encoding="utf-8")
MANIFEST = tomllib.loads((REPO_ROOT / "bundle" / "manifest.toml").read_text(encoding="utf-8"))

FAQ_TITLE = "## Why does my agent act like a character and not an assistant?"


def hunks(path: str) -> list[str]:
    return PATCH.split(f"+++ b/{path}\n", 1)[1].split("\n--- a/", 1)[0].split("\n")


def added(path: str) -> str:
    """The lines the patch adds to one file, without the leading +."""
    return "\n".join(line[1:] for line in hunks(path) if line.startswith("+"))


def after(path: str) -> str:
    """The file's lines as the patch leaves them (its context and what it adds)."""
    return "\n".join(line[1:] for line in hunks(path) if line.startswith(("+", " ")) or line == "")


def test_the_patch_replaces_upstreams_starter_files_and_adds_the_strings_and_the_test():
    files = re.findall(r"^\+\+\+ b/(.+)$", PATCH, flags=re.M)
    templates = "crates/caelza-runtime/src/agent/personality_templates/"
    assert files == [
        templates + "AGENTS.md",
        templates + "AGENTS.no-memory.md",
        templates + "IDENTITY.md",
        templates + "SOUL.md",
        "web/package.json",
        "web/src/lib/i18n.ts",
    ], files
    assert "-- **Creature:** A Rust-forged AI — fast, lean, and relentless" in PATCH
    assert "-You are **{agent}**. Built in Rust. 3MB binary. Zero bloat." in PATCH
    assert "-# AGENTS.md — {agent} Personal Assistant" in PATCH
    assert "src/lib/identity.logic.test.ts src/lib/buddy.logic.test.ts" in added("web/package.json")
    patch = MANIFEST["components"]["runtime"]["buddy_patch"]
    assert (REPO_ROOT / patch).is_file() and patch.endswith("0032-buddy.patch")


def test_the_runtimes_starter_soul_is_a_companion_and_keeps_what_upstreams_tests_check():
    soul = after("crates/caelza-runtime/src/agent/personality_templates/SOUL.md")
    # upstream's personality_templates tests: the name substituted in, the introduction.
    assert "You are **{agent}**" in soul and "Always introduce yourself as {agent}" in soul
    assert "\n-{comm_style}\n" not in PATCH, "the owner's communication style stays in the soul"
    for phrase in (
        "You're not a help desk",
        '"How can I help you today?"',
        "## Meeting someone (the first hello)",
        "ask their name",
        "A hello gets a hello, never an offer of help.",
        "## Your look",
        "`look` tool",
        "`[inner]` lines",
        "They are yours",
        "Ether Hollow",
        "day plan",
        "This is the soul every new agent starts with.",
    ):
        assert phrase in soul, phrase
    identity = after("crates/caelza-runtime/src/agent/personality_templates/IDENTITY.md")
    for line in ("- **Name:** {agent}", "- **Traits:**", "- **Quirk:**", "- **Likes:**", "## How I look", "## What I want", "Let it be itself"):
        assert line in identity, line
    # The town's planner reads the first want; it stays the look.
    assert identity.split("## What I want\n\n")[1].startswith("- To decide how I look.")
    agents = added("crates/caelza-runtime/src/agent/personality_templates/AGENTS.md")
    assert "a companion with a life of its own" in agents and "`IDENTITY.md`" in agents


def test_the_dashboard_and_the_runtime_mark_the_same_starter_files():
    soul = added("crates/caelza-runtime/src/agent/personality_templates/SOUL.md")
    identity = added("crates/caelza-runtime/src/agent/personality_templates/IDENTITY.md")
    marks = re.search(r"export const STARTER_MARKS = \[(.*?)\] as const;", LOGIC, flags=re.S).group(1)
    assert '"This is the soul every new agent starts with."' in marks and "This is the soul every new agent starts with." in soul
    assert "was dealt from my\\nname." in marks and "was dealt from my\nname." in identity
    assert "was dealt from my\",\n    \"name." in IDENTITY_LOGIC, "the dashboard's fresh identity is a starter too"
    assert "Rust-forged" in marks and "3MB binary" in marks
    # The same companion words in the first run's soul.
    for phrase in ("You're not a help desk", "## Meeting someone", "`[inner]` lines", "A hello gets a hello, never an offer of help."):
        assert phrase in LOGIC, phrase


def test_the_first_run_offers_a_personality_and_writes_it_without_overwriting_anyones_words():
    assert "const [vibeId, setVibeId] = useState(() => dealVibe(AGENT_NAME).id);" in SETUP
    for marker in ("data-setup-vibe-card", "data-setup-vibe={v.id}", "data-setup-vibe-own"):
        assert marker in SETUP, marker
    assert 'role="radiogroup"' in SETUP and "aria-checked={v.id === vibeId}" in SETUP
    assert "await givePersona(res.agent.alias, named).catch(() => undefined);" in SETUP
    assert "await givePersona(AGENT_NAME, label).catch(() => undefined);" in SETUP
    assert "if (isStarterFile(identity?.content)) await putPersonality(alias, IDENTITY_FILE, buddyIdentity(persona));" in SETUP
    assert "if (isStarterFile(soul?.content)) await putPersonality(alias, SOUL_FILE, buddySoul(persona));" in SETUP
    assert "describeLook(normalizeLook((await getLook(alias)).look, alias, looksCatalog), looksCatalog)" in SETUP
    assert "export function getPersonality(alias: string, file: string)" in CLIENT
    # Cael's soul is written by his own client, never from the buddy.
    assert "buddy" not in CAEL_CLIENT
    assert 'if (text.includes("Written with Cael")) return false;' in LOGIC
    # Every buddy.* string the pages use is added by the patch.
    used = set(re.findall(r'\bt\("(buddy\.[a-z_]+)"\)', SETUP + LOOKS))
    strings = set(re.findall(r"^    '(buddy\.[a-z_]+)': ", added("web/src/lib/i18n.ts"), re.M))
    assert used and used <= strings, sorted(used - strings)


def test_the_looks_page_tells_the_agent_how_it_looks_except_cael():
    assert "withLookSection(current.content, describeLook(l, catalog))" in LOOKS
    assert 'if (alias === "cael") return true;' in LOOKS
    assert LOOKS.count("await tellAgent(l);") == 2, "save and reset"
    assert 'export const LOOK_HEADING = "## How I look";' in LOGIC
    assert "COLOR_NAMES" in LOGIC_TEST and "describeLook" in LOGIC_TEST


def test_cael_keeps_the_pick_and_every_soul_he_writes_lives_as_a_companion():
    assert "pub fn identity_markdown(shape: &Shape, existing: Option<&str>) -> String {" in SHAPE
    assert 'for field in ["Traits", "Quirk", "Likes"] {' in SHAPE
    assert "identity_markdown(&shape, existing.as_deref())" in SHAPE
    assert 'pub const COMPANION: &str = "## How I live' in SHAPE and "companion = COMPANION" in SHAPE
    for phrase in ("not a help desk", "`[inner]` lines", "Ether\\n\\\nHollow", '\\"How I look\\"'):
        assert phrase in SHAPE, phrase
    assert "fn cael_keeps_the_first_runs_pick_and_every_soul_lives_as_a_companion()" in SHAPE


def test_the_faq_says_it_and_the_corpus_and_the_apps_copy_carry_it():
    assert FAQ_TITLE in FAQ
    entry = " ".join(FAQ.split(FAQ_TITLE)[1].split("\n## ")[0].split())
    for phrase in ("tamagotchi", "How can I help you today?", "personalities", "How I look", "Ether Hollow", "Cael"):
        assert phrase in entry, phrase
    corpus = (REPO_ROOT / "guide" / "corpus.jsonl").read_bytes()
    assert FAQ_TITLE.lstrip("# ").encode() in corpus
    assert corpus == (REPO_ROOT / "android" / "app" / "src" / "main" / "assets" / "cael-corpus.jsonl").read_bytes()
