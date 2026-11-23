"""Cael, the guide: he/him, warm and personable, and the same Cael in every
place his persona is written (the SOUL.md source, the design page, and the
IDENTITY.md the installer writes)."""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOUL = (REPO_ROOT / "guide" / "cael.system.md").read_text()
DESIGN = (REPO_ROOT / "guide" / "CAEL.md").read_text()
SETUP = (REPO_ROOT / "scripts" / "model-setup.sh").read_text()


def identity_card() -> str:
    """The IDENTITY.md heredoc model-setup.sh writes into Cael's workspace."""
    _, _, rest = SETUP.partition("\"$ws/IDENTITY.md\" <<'EOF'\n")
    card, _, _ = rest.partition("\nEOF\n")
    assert card, "model-setup.sh must write Cael's IDENTITY.md"
    return card


def test_cael_is_he_and_lovable_everywhere():
    assert "Cael is a he" in SOUL
    assert "he/him" in DESIGN
    card = identity_card()
    assert "- **Name:** Cael" in card
    assert "- **Pronouns:** he/him" in card
    for word in ("warm", "personable"):
        assert word in card, word
    for phrase in ("never sarcastic", "never scolding"):
        assert phrase in SOUL and phrase in card, phrase
    assert "warm" in SOUL.lower()
    assert "No exclamation marks" not in SOUL  # the old dry register is gone
    assert "never cute" not in DESIGN


def test_cael_explains_and_acts_once_to_shape_the_owners_agent():
    assert "You have one tool,\n`shape_agent`, and that is the only thing you do besides talk." in SOUL
    assert "You do not run\nother tools, change settings, or act for the owner" in SOUL
    # Meeting a new owner: one question at a time, then the one tool call, then "say hello".
    for phrase in ("Meeting a new owner:", "One question at a time", "Ask their name.", "call `shape_agent` once", "say hello to it", "a name is enough"):
        assert phrase in SOUL, phrase
    assert "gives the owner's agent who it is" in identity_card()
    # The runtime side of the same promise: a profile that allows his one tool and nothing else.
    assert "cset risk_profiles.guide.level supervised" in SETUP
    assert "cset risk_profiles.guide.deny_all_tools false" in SETUP
    assert 'cset risk_profiles.guide.allowed_tools' in SETUP and 'cset risk_profiles.guide.auto_approve' in SETUP
    assert "readonly" not in SETUP.split("# --- configure the Runtime")[1].split("# --- Cael's persona")[0]


def heredoc(name: str) -> str:
    """A file model-setup.sh writes into Cael's workspace."""
    _, _, rest = SETUP.partition(f"\"$ws/{name}\" <<'EOF'\n")
    body, _, _ = rest.partition("\nEOF\n")
    assert body, f"model-setup.sh must write Cael's {name}"
    return body


def test_cael_knows_the_owner_is_someone_and_never_says_user():
    # The soul: he asks the owner's name once and never calls anyone "User"; the owner's agent is theirs.
    assert "never call anyone\n\"User\"" in SOUL
    assert "ask it, warmly and once" in SOUL
    assert "Their own agent is theirs, not\nyou" in SOUL
    # His USER.md and AGENTS.md, so the Runtime's templates (which name the owner "User") never fill in.
    cli = (REPO_ROOT / "android" / "app" / "src" / "main" / "java" / "tech" / "enlightenedrepublic" / "caelza" / "runtime" / "CaelzaCli.kt").read_text()
    user = heredoc("USER.md")
    agents = heredoc("AGENTS.md")
    for line in ("# USER.md — the owner", "I don't know my owner's name yet.", "never \"User\"."):
        assert line in user, line
        assert line.replace('"', '\\"') in cli, line
    for line in ("# AGENTS.md — how Cael works", "I run one tool, `shape_agent`, to give the owner's agent who it is when we first meet, and no other; I change no settings."):
        assert line in agents, line
        assert line in cli, line
    # A stock USER.md from an earlier install is replaced, on both installers.
    assert "grep -q '\\*\\*Name:\\*\\* User' \"$ws/USER.md\"" in SETUP
    assert "STOCK_USER.containsMatchIn(user.readText())" in cli


def test_cael_facts_stay_in_step_with_the_runtime():
    # The facts Cael relies on name the real surfaces.
    for fact in ("caelza config set", "Shizuku", "xanima", "http://127.0.0.1:42617"):
        assert fact in SOUL, fact
    # The design page points at the loaded text instead of carrying a stale copy.
    assert "cael.system.md" in DESIGN
    assert "## System prompt (draft)" not in DESIGN
