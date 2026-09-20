"""Tests for cleaning Galaris conversations at the LLM gateway."""

import json
from typing import Any

from app.llm.message_cleanup import clean_request_messages


def _old_user_message(text: str, history_lines: list[str]) -> dict[str, Any]:
    """Reproduce a user message built by build_task_prompt with Hermes context."""
    history = "\n".join(f"- {line}" for line in history_lines)
    return {
        "role": "user",
        "content": (
            "<galaris_role>\nYou will embody a character named **Aster Test**.\n</galaris_role>\n"
            "<galaris_message_context>\n"
            '{"task_id": "0f336215-a34a-4b37-9aa1-27421b5c9755",\n'
            ' "datetime": "2026-07-04T09:12:00+02:00", "weekday": "Saturday",\n'
            ' "user_name": "Nicolas", "user_id": "nicolas",\n'
            ' "location": "Caen", "platform": "talk", "room_id": "room-42",\n'
            ' "recent_attachments": "report.pdf (id 12)", "recent_images": "none"}\n'
            "</galaris_message_context>\n"
            "<execution_briefing>\nNO ISSUES\n</execution_briefing>\n"
            f"<message-or-task>\n{text}\n</message-or-task>\n\n"
            "Recent messages in this room, for context — some may be missing from your own "
            "conversation history (posted by scheduled jobs or other agents). The current "
            "message is delivered separately.\n"
            f"<conversation_context>\n<history>\n{history}\n</history>\n</conversation_context>"
        ),
    }


def _galaris_conversation() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "Hermes system."},
        _old_user_message(
            "Hello, how are you?",
            ["Nicolas: context-only note", "Aster: present!"],
        ),
        {"role": "assistant", "content": "Very well, thank you!"},
        {"role": "assistant", "content": ""},  # Empty flattened Hermes tool turn.
        _old_user_message(
            "Write a weather report.",
            ["Nicolas: context-only note", "Nicolas: Hello, how are you?"],
        ),
        {"role": "assistant", "content": "Here is the weather report."},
        {
            "role": "user",
            "content": (
                "<galaris_role>\nYou will embody **Aster Test**.\n</galaris_role>\n"
                "<galaris_message_context>\n"
                '{"task_id": "6b1d8c1e-0d0f-4c34-9a58-1c1caa6a6d42",\n'
                ' "datetime": "Friday, July 04, 2026 at 10:00:00 (Local time)"}\n'
                "</galaris_message_context>\n"
                "<message-or-task>\nThanks, send it to Vega.\n</message-or-task>\n"
                "<conversation_context>\n<history>\n- Nicolas: Write a weather report.\n"
                "- Vega: I would like the report too\n</history>\n</conversation_context>"
            ),
        },
    ]


def test_untouched_when_not_galaris_format() -> None:
    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Hello!"},
        {"role": "assistant", "content": ""},
    ]

    assert clean_request_messages(messages) is messages


def test_empty_messages_are_dropped() -> None:
    cleaned = clean_request_messages(_galaris_conversation())

    assert all(
        m.get("content") or m.get("tool_calls") for m in cleaned if m["role"] != "tool"
    )


def test_old_user_messages_lose_repeated_sections_and_keep_context_json() -> None:
    cleaned = clean_request_messages(_galaris_conversation())

    old_users = [
        m for m in cleaned
        if m["role"] == "user" and "Hello, how are you?" in str(m["content"])
    ]
    assert old_users
    for message in old_users:
        content = str(message["content"])
        assert "<galaris_role>" not in content
        assert "<execution_briefing>" not in content
        assert "<galaris_message_context>" not in content
        assert "<history>" not in content
        assert "Recent messages in this room" not in content
        # Only essential speaker and time information survives in the compressed line.
        assert "report.pdf" not in content
        assert "task_id" not in content
        assert "platform" not in content
        assert "location" not in content
        # The message tag is unwrapped into plain text below the compressed context.
        assert "<message-or-task>" not in content
        # Minimal JSON context leads with datetime, weekday, user_name, and user_id.
        context_json, _, body = content.partition("\n\n")
        context = json.loads(context_json)
        assert set(context) == {"datetime", "weekday", "user_name", "user_id"}
        assert context["datetime"] == "2026-07-04T09:12:00+02:00"
        assert context["weekday"] == "Saturday"
        assert context["user_name"] == "Nicolas"
        assert context["user_id"] == "nicolas"
        assert "Hello, how are you?" in body
    # The plain text of old messages remains present.
    assert any("Hello, how are you?" in str(m["content"]) for m in old_users)


def test_briefing_is_removed_from_history_but_kept_for_current_message() -> None:
    old = _old_user_message("Old request.", [])
    old["content"] = str(old["content"]).replace("NO ISSUES", "OLD BRIEFING")
    current = _old_user_message("Current request.", [])
    current["content"] = str(current["content"]).replace("NO ISSUES", "CURRENT BRIEFING")
    messages = [
        {"role": "system", "content": "Hermes system."},
        old,
        {"role": "assistant", "content": "Old response."},
        current,
    ]

    cleaned = clean_request_messages(messages)

    old_content = next(
        str(message["content"])
        for message in cleaned
        if "Old request." in str(message.get("content"))
    )
    current_content = str(cleaned[-1]["content"])
    assert "<execution_briefing>" not in old_content
    assert "OLD BRIEFING" not in old_content
    assert "<execution_briefing>\nCURRENT BRIEFING\n</execution_briefing>" in current_content


def test_current_user_message_keeps_structure_and_prunes_known_history() -> None:
    cleaned = clean_request_messages(_galaris_conversation())

    content = str(cleaned[-1]["content"])
    # Preserve the current message structure, including task_id gateway correlation.
    assert "<galaris_role>" in content
    assert "<galaris_message_context>" in content
    assert '"task_id"' in content
    assert "Thanks, send it to Vega." in content
    # Remove a history line already present as a real message.
    assert "- Nicolas: Write a weather report." not in content
    # Preserve a line unknown to the conversation.
    assert "- Vega: I would like the report too" in content
    assert "<history>" in content


def test_current_history_block_removed_when_fully_redundant() -> None:
    messages = _galaris_conversation()
    # Keep only the redundant line in the current message history.
    messages[-1]["content"] = str(messages[-1]["content"]).replace(
        "\n- Vega: I would like the report too", ""
    )

    cleaned = clean_request_messages(messages)

    content = str(cleaned[-1]["content"])
    assert "<history>" not in content
    assert "<conversation_context>" not in content
    assert "Thanks, send it to Vega." in content


def test_history_entries_are_promoted_once_and_deduplicated() -> None:
    cleaned = clean_request_messages(_galaris_conversation())

    promoted = [m for m in cleaned if m["role"] == "user" and str(m["content"]).startswith("Nicolas:") or str(m["content"]).startswith("Aster:")]
    contents = [str(m["content"]) for m in cleaned]

    # The context-only note appears in two history blocks but is promoted only once.
    assert contents.count("Nicolas: context-only note") == 1
    # "Aster: present!" exists nowhere else, so it is promoted.
    assert "Aster: present!" in contents
    # Messages already represented as real turns are not promoted as duplicates.
    assert not any(c == "Nicolas: Hello, how are you?" for c in contents)
    assert not any(c == "Nicolas: Write a weather report." for c in contents)
    # Promoted entries precede the message that carried them.
    assert contents.index("Nicolas: context-only note") < contents.index(
        next(c for c in contents if "Hello, how are you?" in c and c.startswith("{"))
    )
    assert promoted  # At least one effective promotion.


def test_tool_call_pairing_is_preserved() -> None:
    messages = [
        {"role": "system", "content": "s"},
        _old_user_message("Find the Exemple fairy.", ["Nicolas: hello"]),
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": ""},
        {"role": "user", "content": "<message-or-task>\nWhat next?\n</message-or-task>"},
    ]

    cleaned = clean_request_messages(messages)

    roles = [m["role"] for m in cleaned]
    # Preserve both the empty assistant tool call and its empty tool result.
    assert "assistant" in roles
    assert "tool" in roles
    assistant = next(m for m in cleaned if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "c1"


def test_conversation_is_capped_to_most_recent_messages() -> None:
    # Fifty user/assistant turns plus a Galaris marker activate cleanup.
    messages: list[dict[str, Any]] = [{"role": "system", "content": "s"}]
    for i in range(50):
        messages.append({"role": "user", "content": f"<message-or-task>\nmessage {i}\n</message-or-task>"})
        messages.append({"role": "assistant", "content": f"response {i}"})

    cleaned = clean_request_messages(messages)

    non_system = [m for m in cleaned if m["role"] != "system"]
    assert len(non_system) == 30
    # Preserve the most recent messages and keep the system message first.
    assert cleaned[0]["role"] == "system"
    assert "response 49" in str(non_system[-1]["content"])
    assert not any("message 0" in str(m["content"]) for m in non_system)


def test_cap_drops_leading_orphan_tool_results() -> None:
    # If the cap falls after an assistant tool call, remove the orphaned tool result that would
    # otherwise lead the retained window, preserving OpenAI pairing.
    messages: list[dict[str, Any]] = [{"role": "system", "content": "s"}]
    for i in range(29):
        messages.append({"role": "user", "content": f"<message-or-task>\nm{i}\n</message-or-task>"})
        messages.append({"role": "assistant", "content": f"r{i}"})
    # Position a tool pair so the 30-message cap splits it.
    messages.insert(3, {
        "role": "assistant", "content": "",
        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search_web", "arguments": "{}"}}],
    })
    messages.insert(4, {"role": "tool", "tool_call_id": "c1", "content": "result"})

    cleaned = clean_request_messages(messages)

    non_system = [m for m in cleaned if m["role"] != "system"]
    assert len(non_system) <= 30
    assert non_system[0]["role"] != "tool"
