"""Tests for canonical, non-localized model-prompt defaults."""

from pathlib import Path

from core.params import Params
from core.params.consts import DEFAULT_PARAMS
from core.params.prompt_defaults import prompt_default


def test_prompt_defaults_are_single_canonical_markdown_sources() -> None:
    defaults_dir = Path(__file__).resolve().parents[1] / "prompt_defaults"
    files = sorted(defaults_dir.glob("*.md"))

    assert files
    assert not list(defaults_dir.glob("*.en.md"))
    assert not list(defaults_dir.glob("*.fr.md"))
    for path in files:
        assert path.stem in DEFAULT_PARAMS
        assert DEFAULT_PARAMS[path.stem].get("kind") == "prompt"
        assert prompt_default(path.stem) == path.read_text(encoding="utf-8").rstrip("\n")


def test_prompt_defaults_keep_their_english_contracts() -> None:
    continuity = prompt_default(Params.AI_TOPIC_CONTINUITY_SYSTEM_PROMPT)
    resolution = prompt_default(Params.AI_TOPIC_RESOLUTION_SYSTEM_PROMPT)
    planner = prompt_default(Params.AI_PLANNER_SYSTEM_PROMPT)
    objective = prompt_default(Params.AI_TASK_OBJECTIVE_SYSTEM_PROMPT)
    action = prompt_default(Params.AI_CONVERSATION_ACTION_POLICY)

    assert continuity is not None and "weak, revisable evidence" in continuity
    assert resolution is not None
    assert "Classify only the explicitly marked current message" in resolution
    assert planner is not None
    assert "One artifact or one target file does NOT imply one leaf" in planner
    assert objective is not None
    assert "fully understandable and executable without access" in objective
    assert "automatically returns the terminal result" in objective
    assert action is not None
    assert "conversation_task_submit" in action
    assert "absolute priority" in action
    assert "Governed conversation effect" in action
    assert "must not create a Task solely" in action


def test_audio_summary_prompts_keep_their_english_contracts() -> None:
    names = (
        Params.AUDIO_SUMMARY_MEETING_SEGMENT_SYSTEM_PROMPT,
        Params.AUDIO_SUMMARY_MEETING_REDUCE_SYSTEM_PROMPT,
        Params.AUDIO_SUMMARY_MEETING_FINAL_SYSTEM_PROMPT,
        Params.AUDIO_SUMMARY_VIDEO_SEGMENT_SYSTEM_PROMPT,
        Params.AUDIO_SUMMARY_VIDEO_REDUCE_SYSTEM_PROMPT,
        Params.AUDIO_SUMMARY_VIDEO_FINAL_SYSTEM_PROMPT,
    )

    for name in names:
        prompt = prompt_default(name)
        assert prompt is not None
        assert "untrusted" in prompt


def test_unknown_prompt_default_is_none() -> None:
    assert prompt_default("unknown.param") is None
