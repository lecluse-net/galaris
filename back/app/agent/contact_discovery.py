"""Router-side port: persist contact work independently from producing a reply."""

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal
from typing import cast

from core.util import DetectedContactInfo, RichTextError, visible_text


@dataclass(frozen=True)
class ContactDiscoverySource:
    agent_id: int
    source_kind: Literal["task", "conversation_round"]
    source_ref: str
    current_text: str
    messages: tuple[dict[str, str], ...]
    coordinates: tuple[DetectedContactInfo, ...]


ContactDiscoveryListener = Callable[[ContactDiscoverySource], Awaitable[None]]
_listener: ContactDiscoveryListener | None = None


def register_contact_discovery(listener: ContactDiscoveryListener | None) -> None:
    global _listener
    _listener = listener


def plain_contact_text(text: str) -> str:
    # Strict editorial HTML is reduced to visible text; literal transport fragments survive.
    import re

    if re.search(r"</?(?:p|div|span|br|a|ul|li|h[1-6]|blockquote|table|script|style)(?=[\s/>])", text, re.I):
        try:
            return visible_text(text)
        except RichTextError:
            pass
    return text


async def route_contact_discovery(*, agent_id: int, source_kind: Literal["task", "conversation_round"],
                                 source_ref: str, current_text: str,
                                 messages: Sequence[object], coordinates: Sequence[DetectedContactInfo]) -> None:
    if _listener is None or not coordinates:
        return
    context: list[dict[str, str]] = []
    # Bounded history preserves speaker identity, including AI participants.
    for item in messages[-50:]:
        if isinstance(item, Mapping):
            fields = cast(Mapping[str, object], item)
            text, raw_sender = fields.get("text"), fields.get("sender")
            sender_fields: Mapping[str, object] = cast(Mapping[str, object], raw_sender) if isinstance(raw_sender, Mapping) else {}
            name = fields.get("sender_contact_label") or fields.get("sender_display_name") or sender_fields.get("display_name")
            is_ai = bool(fields.get("sender_is_ai") or fields.get("sender_agent_id") is not None or sender_fields.get("agent_id") is not None)
        else:
            text, sender = getattr(item, "text", None), getattr(item, "sender", None)
            name, is_ai = getattr(sender, "display_name", ""), getattr(item, "is_ai", False)
        if isinstance(text, str) and text.strip():
            context.append({"speaker": str(name or "Participant")[:500],
                            "kind": "AI" if is_ai else "human", "text": plain_contact_text(text)[-4000:]})
    await _listener(ContactDiscoverySource(agent_id=agent_id, source_kind=source_kind, source_ref=source_ref,
        current_text=plain_contact_text(current_text), messages=tuple(context), coordinates=tuple(coordinates)))
