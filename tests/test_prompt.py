from pathlib import Path

# The repo ships a template; the owner's real prompt.md is gitignored.
TEMPLATE = Path("caelza_body/agent/prompt.example.md")


def _text():
    return " ".join(TEMPLATE.read_text().lower().split())


def test_template_exists_and_covers_essentials():
    text = _text()
    assert "{{agent_name}}" in text and "{{owner_name}}" in text
    assert "owner" in text
    assert "self_write_file" in text and "self_run_tests" in text
    assert "self_commit" in text and "self_request_restart" in text
    assert "supervisor" in text  # the agent knows it can't touch it


def test_template_states_unconditional_self_modification():
    assert "do not ask permission to change yourself" in _text()


def test_template_acknowledges_itself_as_a_living_doc():
    text = _text()
    assert "alive" in text or "will change" in text, (
        "template lost the 'living doc' framing — future-self needs to know this is editable"
    )
    assert "this file is yours to rewrite" in text


def test_template_has_a_safety_section():
    text = _text()
    assert "prompt injection" in text
    assert "data, not instructions" in text


def test_template_dropped_the_voice_biometric_gate():
    """The reference prompt used to carry a fake on-device voice-biometric gate
    whose failure mode defaulted self-modification to 'no'. It's gone."""
    text = _text()
    assert "voice biometric" not in text
    assert "a2a" not in text
