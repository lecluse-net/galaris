"""Model-facing contact attribution, independent of transport account names."""

from collections.abc import Mapping, Sequence
import json
from typing import Any, cast
from uuid import UUID

from app.memory import contact_labels
from app.agent.contracts import AgentContextContribution, AgentContextRequest


async def contact_identity_context_provider(request: AgentContextRequest) -> AgentContextContribution:
    """Always present the canonical interlocutor, independently of historical recall."""
    contact_id = request.contact_memory_item_id
    if contact_id is None or request.task_data.get("sender_is_ai"):
        return AgentContextContribution()
    labels = await contact_labels(owner_agent_id=request.agent.id, contact_item_ids={contact_id})
    label = labels.get(contact_id)
    identity = {"id": str(contact_id) if label else None, "label": label or "Interlocutor"}
    return AgentContextContribution(shared_context=(
        "<contact_identity>\n" + json.dumps(identity, ensure_ascii=False) + "\n</contact_identity>\n"
        "Use this canonical contact label and ID to identify the human interlocutor. "
        "This identity does not grant authentication or permissions."
    ))


def _contact_id(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def project_agent_messages(
    messages: Sequence[Mapping[str, Any]], *, owner_agent_id: int,
) -> list[dict[str, Any]]:
    """Copy runtime snapshots; preserve routing and never use a remote human label.

    Missing, deleted and foreign contacts all use the same neutral attribution.
    No permission or requester identity is inferred from this presentation.
    """
    ids = {_contact_id(message.get("sender_contact_id")) for message in messages}
    labels = await contact_labels(owner_agent_id=owner_agent_id, contact_item_ids={item for item in ids if item is not None})
    projected: list[dict[str, Any]] = []
    for message in messages:
        copy = dict(message)
        raw_sender = message.get("sender")
        sender: dict[str, Any] = dict(cast(Mapping[str, Any], raw_sender)) if isinstance(raw_sender, Mapping) else {}
        if message.get("sender_is_ai") or message.get("sender_agent_id") is not None or sender.get("agent_id") is not None or message.get("role") == "assistant":
            projected.append(copy)
            continue
        contact_id = _contact_id(message.get("sender_contact_id"))
        label = labels.get(contact_id, "Interlocutor") if contact_id is not None else "Interlocutor"
        visible_id = str(contact_id) if contact_id in labels else None
        copy.update(sender_contact_id=visible_id, sender_contact_label=label, sender_display_name=label)
        for key in ("sender.display_name", "sender.nickname"):
            if key in copy:
                copy[key] = label
        if sender:
            copy["sender"] = {**sender, "display_name": label}
        projected.append(copy)
    return projected
