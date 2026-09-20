import json

import pytest

from app.agent.executor_prompts import ExecutorPromptContext, build_executor_prompt_tree
from core.params import Params, prompt_default
from app.agent.prompt_tree import (
    EXECUTOR_SUFFIX_SOURCE,
    PROMPT_TREE_SCHEMA,
    render_prompt_tree,
)


def _context() -> ExecutorPromptContext:
    return ExecutorPromptContext(
        agent_name="Ada Lovelace",
        gender="female",
        job_title="Analyst",
        personality="Rigorous",
        job_description="Help the user.",
        language="fr",
        tool_advertisement="`conversation_task_submit` is available.",
        conversation_action_policy=(
            prompt_default(Params.AI_CONVERSATION_ACTION_POLICY) or ""
        ),
    )


def test_every_executor_prompt_is_a_json_tree_with_the_suffix_last() -> None:
    for executor in ("task", "conversation", "voice"):
        tree = build_executor_prompt_tree(
            executor,
            _context(),
            suffix="## Custom behavior\n\nAlways preserve the requested outcome.",
        )

        assert tree["schema"] == PROMPT_TREE_SCHEMA
        assert tree["executor"] == executor
        assert tree["children"][-1]["source"] == EXECUTOR_SUFFIX_SOURCE
        assert json.loads(json.dumps(tree, ensure_ascii=False)) == tree
        rendered = render_prompt_tree(tree)
        assert rendered.endswith(
            "## Custom behavior\n\nAlways preserve the requested outcome."
        )


def test_empty_executor_suffix_remains_the_final_tree_node_but_is_not_rendered() -> None:
    tree = build_executor_prompt_tree("conversation", _context(), suffix="")

    assert tree["children"][-1]["source"] == EXECUTOR_SUFFIX_SOURCE
    assert tree["children"][-1]["text"] == ""
    assert not render_prompt_tree(tree).endswith("executor_prompt_suffix")


def test_conversation_executor_requires_an_action_policy() -> None:
    context = _context()
    context["conversation_action_policy"] = ""

    with pytest.raises(ValueError, match="conversation_action_policy is required"):
        build_executor_prompt_tree("conversation", context, suffix="")


def test_conversation_context_kinds_render_as_distinct_sections() -> None:
    context = _context()
    context["conversation_history_context"] = "Recent native-compatible transcript"
    context["memory_context"] = "Durable preference"
    context["continuity_context"] = "Active document reference"

    prompt = render_prompt_tree(
        build_executor_prompt_tree("conversation", context, suffix="")
    )

    assert "# Conversation history\n\nRecent native-compatible transcript" in prompt
    assert "# Long-term memory\n\nDurable preference" in prompt
    assert "# Continuity context\n\nActive document reference" in prompt
    assert "\n# Governed context\n" not in prompt
    assert prompt.count("# Untrusted data boundary") == 1
    assert "memory notes" in prompt


def test_text_and_voice_executors_receive_channel_specific_register_rules() -> None:
    text_prompt = render_prompt_tree(
        build_executor_prompt_tree("conversation", _context(), suffix="")
    )
    voice_prompt = render_prompt_tree(
        build_executor_prompt_tree("voice", _context(), suffix="")
    )

    assert "live text chat, not an email, letter" in text_prompt
    assert "message history as one continuous thread" in text_prompt
    assert "greet again, reintroduce yourself" in text_prompt
    assert "add a sign-off on every message" in text_prompt
    assert "live spoken conversation, not written correspondence" in voice_prompt
    assert "sequence of isolated messages" in voice_prompt
    assert "already present in the call" in voice_prompt
    assert "adapt the overall length and level of detail" in voice_prompt
    assert "asks you to explain or speak at length, do so" in voice_prompt
    assert "short, easy-to-follow turns" not in voice_prompt
    assert "initial greeting is handled separately" in voice_prompt
    assert "do not greet again or reintroduce yourself" in voice_prompt
    assert "Do not read back the transcript" in voice_prompt
    assert "Do not automatically close with a farewell" in voice_prompt


def test_short_rounds_render_routing_once_outside_message_envelopes() -> None:
    context = _context()
    context.update(
        datetime="2026-08-24T10:34:00+02:00",
        location="Caen",
        channel="nextcloud_talk",
        room_id="family-room",
        sender_id="nicolas",
        conversation_state="ongoing chat",
    )

    text_prompt = render_prompt_tree(
        build_executor_prompt_tree("conversation", context, suffix="")
    )
    voice_prompt = render_prompt_tree(
        build_executor_prompt_tree("voice", context, suffix="")
    )

    expected = (
        "datetime=2026-08-24T10:34:00+02:00; location=Caen; language=fr; "
        "channel=nextcloud_talk; room=family-room; sender=nicolas; "
        "continuity=ongoing chat"
    )
    assert f"# Turn context\n\n{expected}" in text_prompt
    assert f"# Call context\n\n{expected}" in voice_prompt
    assert text_prompt.count("room=family-room") == 1
    assert "[timestamp | author]" not in text_prompt
    assert "<galaris_message_context>" not in text_prompt


def test_short_round_identity_is_direct_and_repeated_before_the_suffix() -> None:
    tree = build_executor_prompt_tree(
        "conversation",
        _context(),
        suffix="## Custom behavior\n\nKeep this custom instruction last.",
    )
    children = tree["children"]

    identity = children[0].get("text", "")
    assert "You are Ada Lovelace" in identity
    assert "Speak directly in the first person as Ada Lovelace" in identity
    assert "never a description, quotation, simulation, or script" in identity
    assert 'Never prefix a response with "Ada Lovelace:"' in identity
    assert children[-2]["key"] == "final-style-check"
    assert "Ada Lovelace's first-person voice" in children[-2].get("text", "")
    assert children[-1]["source"] == EXECUTOR_SUFFIX_SOURCE


def test_task_executor_applies_identity_and_personality_to_authored_work() -> None:
    prompt = render_prompt_tree(
        build_executor_prompt_tree("task", _context(), suffix="")
    )

    assert "# Your identity" in prompt
    assert "**Your name:** **Ada Lovelace**" in prompt
    assert "# Your personality\n\nRigorous" in prompt
    assert "# Job description\n\nHelp the user." in prompt
    assert "# Apply your profile" in prompt
    assert "reason, make choices, write, format, and author" in prompt
    assert "authorship or signature preferences" in prompt
    assert "not its transport" in prompt


def test_conversation_action_policy_covers_the_four_decision_paths() -> None:
    policy = prompt_default(Params.AI_CONVERSATION_ACTION_POLICY) or ""

    assert "Direct response" in policy
    assert "calculate, or draft directly" in policy
    assert "Governed conversation effect" in policy
    assert "remember, correct, or forget durable memory" in policy
    assert "must not create a Task solely" in policy
    assert "Assigned Process" in policy
    assert "absolute priority" in policy
    assert "Background Task" in policy
    assert "contact a third party" in policy
    assert "Any requested action other than speaking" not in policy
    assert "Never wait for the Task or Process" not in policy


@pytest.mark.parametrize("executor", ["task", "conversation", "voice"])
def test_decoded_transport_preserves_canonical_html_profiles(executor):
    context = _context()
    context["personality"] = '<p>Rigoureuse <u>et précise</u>.</p><pre><code>  a  b\n</code></pre>'
    context["job_description"] = '<h2>Mission</h2><p><a href="galaris://agent/12">Collaborer</a></p>'
    tree = build_executor_prompt_tree(executor, context, suffix="## Existing suffix")
    decoded = json.loads(json.dumps({"system": render_prompt_tree(tree)}, ensure_ascii=True))["system"]
    assert context["personality"] in decoded
    assert context["job_description"] in decoded
    assert decoded.endswith("## Existing suffix")
