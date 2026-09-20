"""Compact conversation context rendering for agentic routing and planning."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, Protocol, cast


_LINKED_OBJECTIVE_PROMPT_CHARS = 250
_LINKED_RESOURCE_PROMPT_LIMIT = 10


class ConversationContextSource(Protocol):
    """Read-only conversation fields shared by persisted tasks and run DTOs."""

    @property
    def data(self) -> Mapping[str, Any] | None: ...

    @property
    def messages(self) -> Sequence[object] | None: ...

    @property
    def message_platform(self) -> str | None: ...

    @property
    def objective(self) -> str | None: ...


_CLOSED_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_OPEN_CODE_FENCE_RE = re.compile(r"```.*$", re.DOTALL)
_LEADING_MESSAGE_METADATA_RE = re.compile(
    r"^\s*\[\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(?::\d{2})?"
    r"(?:Z|[+-]\d{2}:?\d{2})?\s*\|\s*[^\]\r\n|]+"
    r"(?:\s*\|\s*(?:AI|human))?\s*\]\s*",
    re.IGNORECASE,
)
_LEADING_MESSAGE_CONTEXT_RE = re.compile(
    r"^\s*<galaris_message_context>.*?</galaris_message_context>\s*",
    re.DOTALL,
)


def strip_fenced_code_blocks(text: str) -> str:
    """Remove Markdown fenced code blocks from history text."""
    without_closed = _CLOSED_CODE_FENCE_RE.sub("[code block omitted]", text)
    return _OPEN_CODE_FENCE_RE.sub("[code block omitted]", without_closed)


def strip_leading_message_metadata(text: str) -> str:
    """Remove an accidentally echoed history cartouche from a delivered answer."""

    without_context = _LEADING_MESSAGE_CONTEXT_RE.sub("", text, count=1)
    return _LEADING_MESSAGE_METADATA_RE.sub("", without_context, count=1)


class LeadingMessageMetadataFilter:
    """Hold a possible streamed history cartouche until it can be discarded safely."""

    def __init__(self) -> None:
        self._pending = ""
        self._decided = False

    def feed(self, content: str) -> str:
        if self._decided or not content:
            return content
        self._pending += content
        stripped = strip_leading_message_metadata(self._pending)
        if stripped != self._pending:
            self._decided = True
            self._pending = ""
            return stripped

        candidate = self._pending.lstrip()
        if (
            not candidate.startswith("[")
            or "]" in candidate
            or "\n" in candidate
            or len(candidate) > 256
        ):
            self._decided = True
            released = self._pending
            self._pending = ""
            return released
        return ""

    def finish(self) -> str:
        released = strip_leading_message_metadata(self._pending)
        self._pending = ""
        self._decided = True
        return released


def _as_mapping(value: object) -> Mapping[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    return cast(Mapping[str, object], value)


def current_message_data(
    message: Mapping[str, object],
    *,
    language: str | None = None,
) -> dict[str, object]:
    """Return the complete canonical current-message snapshot plus legacy aliases."""

    data = dict(message)
    sender = message.get("sender")
    sender_data = _as_mapping(sender) if sender is not None else None
    current_id = (
        message.get("external_message_id")
        or message.get("id")
        or message.get("messenger_message_id")
    )
    data.update(
        {
            "id": current_id,
            "message_id": current_id,
            "text": message.get("text"),
            "timestamp": message.get("timestamp") or message.get("time"),
            "sender.display_name": (
                message.get("sender_display_name")
                or (sender_data.get("display_name") if sender_data is not None else None)
            ),
            "sender.id": (
                message.get("sender_external_id")
                or (sender_data.get("id") if sender_data is not None else None)
            ),
            "sender_is_ai": bool(
                message.get("sender_is_ai")
                or message.get("sender_agent_id") is not None
                or message.get("role") == "assistant"
            ),
        }
    )
    if language is not None:
        data["language"] = language
    return data


def message_text(message: object) -> str:
    mapping = _as_mapping(message)
    text = mapping.get("text") if mapping is not None else getattr(message, "text", None)
    return text.strip() if isinstance(text, str) else ""


def message_attachment_lines(message: object) -> list[str]:
    """Render canonical file references carried by one history message."""

    mapping = _as_mapping(message)
    raw_attachments = (
        mapping.get("attachments")
        if mapping is not None
        else getattr(message, "attachments", None)
    )
    if not isinstance(raw_attachments, Sequence) or isinstance(
        raw_attachments, (str, bytes)
    ):
        return []
    attachment_items = cast(Sequence[object], raw_attachments)
    lines: list[str] = []
    for raw in attachment_items:
        attachment = _as_mapping(raw)
        uri = (
            attachment.get("uri")
            if attachment is not None
            else getattr(raw, "uri", None)
        )
        name = (
            attachment.get("name")
            if attachment is not None
            else getattr(raw, "name", None)
        )
        if not uri:
            continue
        label = str(name or "file").strip() or "file"
        lines.append(f"[file: {label}] {uri}")
    return lines


def message_history_text(message: object) -> str:
    """Combine message prose and its files without detaching either from history."""

    parts = [message_text(message), *message_attachment_lines(message)]
    return "\n".join(part for part in parts if part)


def message_prompt(
    message: object,
    *,
    fallback_text: str = "",
) -> str:
    """Render one provider message with a compact visible author/time envelope."""

    content = message_history_text(message).strip() or fallback_text.strip()
    return f"{message_history_prefix(message)}{content}".rstrip()


def message_history_prefix(message: object) -> str:
    """Render author/time metadata that provider message metadata does not expose."""

    mapping = _as_mapping(message)
    sender = (
        mapping.get("sender")
        if mapping is not None
        else getattr(message, "sender", None)
    )
    sender_mapping = _as_mapping(sender) if sender is not None else None
    name = (
        (
            sender_mapping.get("display_name")
            if sender_mapping is not None
            else getattr(sender, "display_name", None)
        )
        if sender is not None
        else None
    ) or (
        mapping.get("sender_display_name")
        if mapping is not None
        else getattr(message, "sender_display_name", None)
    )
    sender_id = (
        (
            sender_mapping.get("id")
            if sender_mapping is not None
            else getattr(sender, "id", None)
        )
        if sender is not None
        else None
    ) or (
        mapping.get("sender_external_id")
        if mapping is not None
        else getattr(message, "sender_external_id", None)
    )
    raw_timestamp = (
        mapping.get("timestamp") or mapping.get("time")
        if mapping is not None
        else getattr(message, "timestamp", None) or getattr(message, "time", None)
    )
    try:
        epoch = int(str(raw_timestamp or 0))
    except (TypeError, ValueError):
        epoch = 0
    if epoch <= 0:
        return ""
    timestamp = (
        datetime.fromtimestamp(epoch, tz=timezone.utc)
        .astimezone()
        .isoformat(timespec="minutes")
    )
    author = (
        _compact_metadata_value(name)
        if name
        else (
            f"id:{_compact_metadata_value(sender_id)}"
            if sender_id
            else "unknown"
        )
    )
    return f"[{timestamp} | {author}] "


def _compact_metadata_value(value: object) -> str:
    """Keep an untrusted author label on one unambiguous envelope line."""

    return " ".join(str(value).replace("|", "/").replace("]", ")").split())


def _task_resource_uri(value: object) -> str:
    raw = str(value or "").strip()
    if raw.startswith("galaris://task/"):
        return raw
    return f"galaris://task/{raw}"


def linked_work_context(items: Sequence[Mapping[str, object]]) -> str:
    """Render the canonical bounded Task projection for every conversation runtime."""

    lines: list[str] = []
    for item in items:
        task_uri = _task_resource_uri(item.get("resource_uri") or item.get("task_id"))
        line = (
            f"- task={task_uri} "
            f"revision={item.get('revision')} "
            f"state={item.get('operational_state') or item.get('status')} "
            f"amendable={str(bool(item.get('amendable'))).lower()} "
            f"label={item.get('label')}"
        )
        created_at = str(item.get("created_at") or "").strip()
        state_since = str(item.get("state_since") or "").strip()
        if created_at or state_since:
            line += (
                f"\n  created={created_at or '?'} "
                f"state_since={state_since or '?'}"
            )
        objective = str(item.get("objective") or "").strip()[
            :_LINKED_OBJECTIVE_PROMPT_CHARS
        ]
        if objective:
            line += f"\n  objective: {objective}"
        waits = item.get("waits")
        if isinstance(waits, list):
            for raw_wait in cast(list[object], waits)[:3]:
                wait = _as_mapping(raw_wait)
                if wait is None:
                    continue
                line += (
                    f"\n  waiting: kind={wait.get('kind')} "
                    f"peer={wait.get('peer_display') or wait.get('target_agent_id') or '?'} "
                    f"question={wait.get('question') or ''} "
                    f"deadline={wait.get('deadline') or ''}"
                )
        blocker = str(item.get("amend_blocker") or "").strip()
        if blocker:
            line += f"\n  amend_blocker: {blocker}"
        resources = item.get("working_set")
        if isinstance(resources, list):
            for raw_resource in cast(list[object], resources)[
                :_LINKED_RESOURCE_PROMPT_LIMIT
            ]:
                resource = _as_mapping(raw_resource)
                if resource is None:
                    continue
                line += (
                    f"\n  resource: role={resource.get('role')} "
                    f"type={resource.get('resource_type')} "
                    f"reference={resource.get('reference')} "
                    f"revision={resource.get('revision') or ''}"
                )
        lines.append(line)
    return "\n".join(lines)


def compact_text(text: str, max_chars: int, *, strip_code_blocks: bool = True) -> str:
    source = strip_fenced_code_blocks(text) if strip_code_blocks else text
    clean = " ".join(source.strip().split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3].rstrip() + "..."


def message_line(
    message: object,
    *,
    max_chars: int,
    strip_code_blocks: bool = True,
) -> str:
    mapping = _as_mapping(message)
    sender = mapping.get("sender") if mapping is not None else getattr(message, "sender", None)
    sender_mapping = _as_mapping(sender) if sender is not None else None
    role = str(mapping.get("role") or "") if mapping is not None else ""
    who = (
        (
            (sender_mapping.get("display_name") or sender_mapping.get("id"))
            if sender_mapping is not None
            else (getattr(sender, "display_name", None) or getattr(sender, "id", None))
        )
        if sender is not None
        else None
    ) or (
        mapping.get("sender_display_name")
        or mapping.get("sender_external_id")
        if mapping is not None
        else getattr(message, "sender_display_name", None)
        or getattr(message, "sender_external_id", None)
    ) or ("Agent" if role == "assistant" else "Interlocutor")
    raw_timestamp = (
        mapping.get("timestamp") or mapping.get("time")
        if mapping is not None
        else getattr(message, "timestamp", None) or getattr(message, "time", None)
    )
    timestamp = ""
    try:
        epoch = int(str(raw_timestamp or 0))
    except (TypeError, ValueError):
        epoch = 0
    if epoch > 0:
        timestamp = (
            datetime.fromtimestamp(epoch, tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    is_ai = bool(
        role == "assistant"
        or (
            mapping.get("sender_is_ai") or mapping.get("sender_agent_id") is not None
            if mapping is not None
            else getattr(message, "sender_is_ai", False)
            or getattr(message, "sender_agent_id", None) is not None
        )
    )
    content = compact_text(
        message_history_text(message),
        max_chars,
        strip_code_blocks=strip_code_blocks,
    )
    if timestamp:
        return f"[{timestamp} | {who} | {'AI' if is_ai else 'human'}] {content}"
    return f"{who}: {content}"


def is_current_message(
    task: ConversationContextSource,
    message: object,
    index: int,
    total: int,
) -> bool:
    data = task.data or {}
    current_id = str(data.get("id") or data.get("message_id") or "")
    mapping = _as_mapping(message)
    raw_message_id = (
        mapping.get("id") or mapping.get("external_message_id")
        if mapping is not None
        else getattr(message, "id", None)
        or getattr(message, "external_message_id", "")
    )
    message_id = str(raw_message_id or "")
    if current_id and message_id and message_id == current_id:
        return True
    if task.message_platform == "openai" and index == total - 1:
        return True

    objective = str(task.objective or "").strip()
    text = message_text(message)
    return bool(text and index == total - 1 and text == objective)


def current_message_line(
    task: ConversationContextSource,
    messages: Sequence[object],
    *,
    max_chars: int,
) -> str:
    if task.data is not None:
        current = message_history_text(task.data)
        sender = _as_mapping(task.data.get("sender"))
        who = (
            task.data.get("sender.display_name")
            or task.data.get("sender.id")
            or task.data.get("sender_display_name")
            or task.data.get("sender_external_id")
            or (sender.get("display_name") if sender is not None else None)
            or (sender.get("id") if sender is not None else None)
            or "Interlocutor"
        )
        if current:
            raw_timestamp = task.data.get("timestamp") or task.data.get("time")
            try:
                epoch = int(str(raw_timestamp or 0))
            except (TypeError, ValueError):
                epoch = 0
            if epoch > 0:
                timestamp = (
                    datetime.fromtimestamp(epoch, tz=timezone.utc)
                    .astimezone()
                    .strftime("%Y-%m-%d %H:%M")
                )
                role = "AI" if bool(task.data.get("sender_is_ai")) else "human"
                return (
                    f"[{timestamp} | {who} | {role}] "
                    f"{compact_text(current, max_chars, strip_code_blocks=False)}"
                )
            return f"{who}: {compact_text(current, max_chars, strip_code_blocks=False)}"

    for message in reversed(messages):
        if message_history_text(message):
            return message_line(message, max_chars=max_chars, strip_code_blocks=False)
    return ""


def conversation_context_block(
    task: ConversationContextSource,
    *,
    max_messages: int = 10,
    max_chars: int = 500,
    include_current: bool = True,
    messages_override: Sequence[object] | None = None,
) -> str:
    """Render shared compact history and optional current-message context."""
    source_messages = task.messages if messages_override is None else messages_override
    messages = list(source_messages or ())
    selected_previous, _ = previous_message_lines(
        task,
        max_messages=max_messages,
        max_chars=max_chars,
        messages_override=messages,
    )
    current = (
        current_message_line(task, messages, max_chars=max_chars)
        if include_current
        else ""
    )

    sections: list[str] = []
    if selected_previous:
        history = "\n".join(f"- {line}" for line in selected_previous)
        sections.append(f"<history>\n{history}\n</history>")
    if current:
        sections.append(f"<current_message>\n{current}\n</current_message>")

    if not sections:
        return ""
    return "<conversation_context>\n" + "\n\n".join(sections) + "\n</conversation_context>"


def previous_message_lines(
    task: ConversationContextSource,
    *,
    max_messages: int,
    max_chars: int,
    messages_override: Sequence[object] | None = None,
) -> tuple[list[str], int]:
    source_messages = task.messages if messages_override is None else messages_override
    messages = list(source_messages or ())
    total = len(messages)
    previous = [
        message_line(message, max_chars=max_chars, strip_code_blocks=True)
        for index, message in enumerate(messages)
        if message_history_text(message)
        and not is_current_message(task, message, index, total)
    ]
    selected = previous[-max_messages:]
    return selected, len(previous) - len(selected)
