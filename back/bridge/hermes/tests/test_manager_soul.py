from types import SimpleNamespace

from bridge.hermes.manager import _build_soul_content, _sanitize_soul_text


def test_sanitize_soul_text_removes_invisible_unicode_and_keeps_newlines() -> None:
    text = "A\u200dB\u200b\nC\tD\x00E"

    assert _sanitize_soul_text(text) == "AB\nC\tDE"


def test_build_soul_content_sanitizes_agent_identity_fields() -> None:
    agent = SimpleNamespace(
        title=SimpleNamespace(label="Dr\u200d"),
        first_name="Ali\u200bce",
        last_name="Du\x00pont",
        job_title="AI Engineer\u200d",
        personality="<p>Rigoureuse\u200d</p><p>Curieuse</p>",
        job_description="<p>Build reliable\u200d agents</p>",
    )

    content = _build_soul_content(agent)

    assert agent.personality in content
    assert agent.job_description in content
    assert "\u200b" not in content
    assert "\x00" not in content
    assert "Alice" in content
    assert "Dupont" in content
    assert "AI Engineer" in content
