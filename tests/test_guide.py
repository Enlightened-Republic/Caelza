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


def test_cael_explains_and_never_acts():
    assert "You do not run tools, change\nsettings, or act for the owner" in SOUL
    assert "never acts" in identity_card()
    # The runtime side of the same promise: a read-only profile with no tools.
    assert "cset risk_profiles.guide.level readonly" in SETUP
    assert "cset risk_profiles.guide.deny_all_tools true" in SETUP


def test_cael_facts_stay_in_step_with_the_runtime():
    # The facts Cael relies on name the real surfaces.
    for fact in ("caelza config set", "Shizuku", "xanima", "http://127.0.0.1:42617"):
        assert fact in SOUL, fact
    # The design page points at the loaded text instead of carrying a stale copy.
    assert "cael.system.md" in DESIGN
    assert "## System prompt (draft)" not in DESIGN
