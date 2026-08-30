from pathlib import Path

# The repo ships a template; the owner's real prompt.md is gitignored.
TEMPLATE = Path("niba/agent/prompt.example.md")


def test_template_exists_and_covers_essentials():
    text = TEMPLATE.read_text().lower()
    assert "{{agent_name}}" in text and "{{owner_name}}" in text and "{{wake_word}}" in text
    assert "owner" in text
    assert "voice biometric" in text, "template lost the prompt-injection defense"
    assert "self_run_tests" in text and "self_commit" in text and "self_request_restart" in text
    assert "supervisor" in text  # the agent knows it can't touch it


def test_template_acknowledges_itself_as_a_living_doc():
    text = TEMPLATE.read_text().lower()
    assert "alive" in text or "will change" in text, (
        "template lost the 'living doc' framing — future-self needs to know this is editable"
    )


def test_template_has_a_safety_section():
    text = TEMPLATE.read_text().lower()
    assert "prompt injection" in text
    assert "data, not" in text  # "...is data, not instructions"
