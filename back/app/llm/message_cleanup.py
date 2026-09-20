"""Clean Galaris conversations before storing and sending them to an LLM gateway.

Task prompts accumulate in agent sessions because each earlier user message embeds the agent
role, metadata, and room history again. This module removes empty messages, compacts prior user
turns, promotes removed history entries into real deduplicated user messages, prunes redundant
history from the current turn, and caps recent non-system messages without splitting tool-call
pairs. Payloads without Galaris tags are returned untouched because they may come from external
clients whose format Galaris does not own.
"""

from __future__ import annotations

import json
import re
from typing import Any, cast

from core.util import as_dict, as_list

# Tags produced by ``build_task_prompt`` in every language. ``role-and-context`` is the legacy
# name retained for active sessions created before the rename.
_GALARIS_TAGS = (
    "<galaris_role>",
    "<galaris_message_context>",
    "<message-or-task>",
    "<role-and-context>",
    "<reply_contract>",
    "<execution_briefing>",
)

# Maximum number of recent non-system messages sent to the model.
_MAX_MESSAGES = 30

_STRIP_BLOCK_RES = [
    re.compile(r"<galaris_role>.*?</galaris_role>\s*", re.DOTALL),
    # Legacy role-section name.
    re.compile(r"<role-and-context>.*?</role-and-context>\s*", re.DOTALL),
    # A fixed delivery contract should not accumulate on every turn.
    re.compile(r"<reply_contract>.*?</reply_contract>\s*", re.DOTALL),
    # Only the current turn's execution briefing should guide the agent.
    re.compile(r"<execution_briefing>.*?</execution_briefing>\s*", re.DOTALL),
    re.compile(r"<history>.*?</history>\s*", re.DOTALL),
    # Legacy metadata section removed without extraction.
    re.compile(r"<metadata>.*?</metadata>\s*", re.DOTALL),
]
_MESSAGE_CONTEXT_RE = re.compile(
    r"<galaris_message_context>(.*?)</galaris_message_context>\s*", re.DOTALL
)
_HISTORY_RE = re.compile(r"<history>(.*?)</history>", re.DOTALL)
# Unwrap the message tag so only raw message text remains.
_MESSAGE_OR_TASK_RE = re.compile(r"<message-or-task>\s*(.*?)\s*</message-or-task>", re.DOTALL)
# Keep only identity and time context from a completed turn.
_CONTEXT_KEPT_KEYS = ("datetime", "weekday", "user_name", "user_id")
# Remove a conversation wrapper that became empty after history removal.
_EMPTY_CONVERSATION_CONTEXT_RE = re.compile(r"<conversation_context>\s*</conversation_context>\s*")
# Remove the Hermes history introduction when its block is gone.
_HISTORY_INTRO_RE = re.compile(
    r"Recent messages in this room[^\n]*\n?(?:[^\n]*delivered separately\.\s*)?"
)
_BLANK_LINES_RE = re.compile(r"\n{3,}")


def _text_of(content: Any) -> str:
    """Extract text from OpenAI string or multipart content."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in as_list(content):
            if isinstance(item, dict):
                value = as_dict(item).get("text")
                if isinstance(value, str):
                    parts.append(value)
        return "\n".join(parts)
    return ""


def _has_payload(message: dict[str, Any]) -> bool:
    """Return whether a message carries text, parts, or tool calls."""
    if as_list(message.get("tool_calls")):
        return True
    content = message.get("content")
    if isinstance(content, list):
        return bool(as_list(content))
    return bool(_text_of(content).strip())


def _normalize(text: str) -> str:
    return " ".join(text.strip().split()).lower()


def _compress_context(inner: str) -> str:
    """Reduce a context object to the keys useful after a turn completes.

    Legacy bullet lists using the same technical key names are supported. Older localized labels
    intentionally do not match and are discarded.
    """
    body = inner.strip()
    entries: dict[str, Any] = {}
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        entries = {str(key): value for key, value in cast(dict[str, Any], parsed).items()}
    else:  # Legacy ``- key: value`` bullets.
        for line in body.splitlines():
            item = line.strip().removeprefix("- ").strip()
            if item:
                key, _, value = item.partition(":")
                entries[key.strip().lower().replace(" ", "_")] = value.strip()

    kept = {
        key: entries[key]
        for key in _CONTEXT_KEPT_KEYS
        if key in entries and entries[key] is not None and str(entries[key]).strip()
    }
    return json.dumps(kept, ensure_ascii=False, indent=2) if kept else ""


def _history_entries(content: str) -> list[str]:
    """Extract ``- Author: text`` entries from all history blocks."""
    entries: list[str] = []
    for match in _HISTORY_RE.finditer(content):
        for line in match.group(1).splitlines():
            line = line.strip()
            if line.startswith("- ") and line.removeprefix("- ").strip():
                entries.append(line.removeprefix("- ").strip())
    return entries


def _clean_old_user_content(content: str) -> str:
    """Strip Galaris wrappers from an old user message and prepend compact context."""
    context_match = _MESSAGE_CONTEXT_RE.search(content)
    compressed = _compress_context(context_match.group(1)) if context_match else ""

    cleaned = _MESSAGE_CONTEXT_RE.sub("", content)
    for pattern in _STRIP_BLOCK_RES:
        cleaned = pattern.sub("", cleaned)
    cleaned = _MESSAGE_OR_TASK_RE.sub(lambda m: m.group(1), cleaned)
    cleaned = _EMPTY_CONVERSATION_CONTEXT_RE.sub("", cleaned)
    cleaned = _HISTORY_INTRO_RE.sub("", cleaned)
    cleaned = _BLANK_LINES_RE.sub("\n\n", cleaned).strip()

    return f"{compressed}\n\n{cleaned}".strip() if compressed else cleaned


def _cap_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep the newest non-system messages while preserving every system message.

    Leading orphan tool results are removed after truncation because the OpenAI protocol requires
    their assistant tool call to remain present.
    """
    system = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    if len(rest) <= _MAX_MESSAGES:
        return messages
    rest = rest[-_MAX_MESSAGES:]
    while rest and rest[0].get("role") == "tool":
        rest.pop(0)
    return [*system, *rest]


def _prune_current_history(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove already-known lines from the current message's history block.

    This runs after message capping so history whose original turn was truncated remains useful.
    """
    user_indexes = [i for i, m in enumerate(messages) if m.get("role") == "user"]
    if not user_indexes:
        return messages
    index = user_indexes[-1]
    current = messages[index]
    content = current.get("content")
    if not isinstance(content, str) or "<history>" not in content:
        return messages

    haystacks = [
        _normalize(_text_of(m.get("content")))
        for i, m in enumerate(messages)
        if i != index
    ]

    def _prune_block(match: "re.Match[str]") -> str:
        kept: list[str] = []
        for line in match.group(1).splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                entry = stripped.removeprefix("- ").strip()
                if _entry_already_present(entry, haystacks):
                    continue
            if stripped:
                kept.append(line)
        if not kept:
            return ""
        return "<history>\n" + "\n".join(kept) + "\n</history>"

    new_content = _HISTORY_RE.sub(_prune_block, content)
    if new_content == content:
        return messages

    new_content = _EMPTY_CONVERSATION_CONTEXT_RE.sub("", new_content)
    if "<history>" not in new_content:
        new_content = _HISTORY_INTRO_RE.sub("", new_content)
    new_content = _BLANK_LINES_RE.sub("\n\n", new_content).strip()

    replaced = dict(current)
    replaced["content"] = new_content
    return [*messages[:index], replaced, *messages[index + 1:]]


def _entry_already_present(entry: str, haystacks: list[str]) -> bool:
    """Return whether a normalized history entry is already present.

    History text may be compacted or truncated, so comparison uses an included text prefix.
    """
    _, _, text = entry.partition(":")
    needle = _normalize(text).removesuffix("...").strip()
    if not needle:
        return True
    probe = needle if len(needle) <= 120 else needle[:120]
    return any(probe in haystack for haystack in haystacks)


def clean_request_messages(messages: Any) -> Any:
    """Clean an OpenAI message array built by Galaris.

    Return the original array when no Galaris format is detected.
    """
    original: Any = messages
    if not isinstance(messages, list):
        return original
    typed = [as_dict(m) for m in as_list(messages) if isinstance(m, dict)]
    if len(typed) != len(as_list(messages)):
        return original  # Preserve unknown payloads containing non-dictionary elements.

    # Require at least one Galaris-formatted user message.
    if not any(
        message.get("role") == "user"
        and any(tag in _text_of(message.get("content")) for tag in _GALARIS_TAGS)
        for message in typed
    ):
        return original

    # Remove empty messages while preserving tool-call/result pairs.
    kept = [
        message
        for message in typed
        if message.get("role") == "tool" or _has_payload(message)
    ]

    # Clean every user message except the current one.
    user_indexes = [i for i, m in enumerate(kept) if m.get("role") == "user"]
    last_user_index = user_indexes[-1] if user_indexes else -1

    cleaned: list[dict[str, Any]] = []
    pending_entries: list[tuple[int, list[str]]] = []  # (insertion index, entries)
    for index, message in enumerate(kept):
        if (
            message.get("role") == "user"
            and index != last_user_index
            and isinstance(message.get("content"), str)
        ):
            content = str(message.get("content"))
            entries = _history_entries(content)
            new_content = _clean_old_user_content(content)
            if not new_content:
                if entries:
                    pending_entries.append((len(cleaned), entries))
                continue  # Drop a message reduced to empty content.
            replaced = dict(message)
            replaced["content"] = new_content
            if entries:
                pending_entries.append((len(cleaned), entries))
            cleaned.append(replaced)
        else:
            cleaned.append(message)

    if not pending_entries:
        return _prune_current_history(_cap_messages(cleaned))

    # Promote history entries to deduplicated messages in block order.
    haystacks = [_normalize(_text_of(m.get("content"))) for m in cleaned]
    promoted_keys: set[str] = set()
    result: list[dict[str, Any]] = []
    entries_by_position: dict[int, list[str]] = {}
    for position, entries in pending_entries:
        entries_by_position.setdefault(position, []).extend(entries)

    for index, message in enumerate(cleaned):
        for entry in entries_by_position.get(index, []):
            key = _normalize(entry).removesuffix("...")
            if key in promoted_keys or _entry_already_present(entry, haystacks):
                continue
            promoted_keys.add(key)
            result.append({"role": "user", "content": entry})
        result.append(message)
    for entry in entries_by_position.get(len(cleaned), []):
        key = _normalize(entry).removesuffix("...")
        if key not in promoted_keys and not _entry_already_present(entry, haystacks):
            promoted_keys.add(key)
            result.append({"role": "user", "content": entry})

    return _prune_current_history(_cap_messages(result))
