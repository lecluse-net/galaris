"""Validated file projections and conditional edits of private canonical contacts."""

import hashlib
import json
from uuid import UUID

from pydantic import JsonValue, TypeAdapter
from app.memory import MemoryConflictError, MemoryNotFoundError

from .directory import lock_contact_directory
from .schemas import ContactRead, ContactUpdate
from .service import get_contact, list_contacts, update_contact


def _payload(contact: ContactRead) -> dict[str, object]:
    payload = contact.model_dump(mode="json", exclude_none=True)
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    payload["etag"] = '"' + hashlib.sha256(serialized.encode("utf-8")).hexdigest() + '"'
    return payload


async def read_contact_resource(
    contact_item_id: UUID, *, actor_agent_id: int,
) -> dict[str, object] | None:
    try:
        contact = await get_contact(agent_id=actor_agent_id, contact_item_id=contact_item_id)
    except MemoryNotFoundError:
        return None
    return _payload(contact)


async def write_contact_resource(
    contact_item_id: UUID, *, actor_agent_id: int, content: bytes, expected_etag: str | None,
) -> dict[str, object]:
    """Apply only editable fields, comparing the snapshot under the contact row lock."""
    if len(content) > 1_000_000:
        raise ValueError("A contact JSON update must not exceed 1,000,000 bytes.")
    update = TypeAdapter(dict[str, JsonValue]).validate_json(content)
    await lock_contact_directory(actor_agent_id)
    # Reject foreign references before acquiring their row lock.
    await get_contact(agent_id=actor_agent_id, contact_item_id=contact_item_id)
    contact = await get_contact(agent_id=actor_agent_id, contact_item_id=contact_item_id, for_update=True)
    current = _payload(contact)
    if not expected_etag:
        raise ValueError("expected_etag from file_read or file_info is required for Contact updates.")
    if expected_etag != current["etag"]:
        raise MemoryConflictError("Contact changed; call file_read before retrying with its current expected_etag.")
    for key, value in update.items():
        if key not in {"display_name", "coordinates"} and (key not in current or value != current[key]):
            raise ValueError(f"Contact field {key!r} is read-only or unknown.")
    if not {"display_name", "coordinates"}.intersection(update):
        raise ValueError("Supply display_name or coordinates to update a Contact.")
    coordinates = update.get("coordinates")
    if isinstance(coordinates, dict):
        coordinates = {**contact.coordinates.model_dump(mode="json"), **coordinates}
    data = ContactUpdate.model_validate({"display_name": update.get("display_name", contact.display_name),
                                         "coordinates": coordinates})
    return _payload(await update_contact(contact_item_id=contact_item_id, data=data))


async def list_contact_resources(
    *, actor_agent_id: int, query: str = "", offset: int = 0, limit: int = 100,
) -> list[dict[str, object]]:
    # File providers need one lookahead row beyond their 500-entry page. Keep
    # the directory's public page bound and fetch that extra row only if needed.
    bounded_limit = max(1, min(limit, 501))
    position = max(0, offset)
    payloads: list[dict[str, object]] = []
    while len(payloads) < bounded_limit:
        page = await list_contacts(
            agent_id=actor_agent_id, query=query, offset=position,
            limit=min(500, bounded_limit - len(payloads)),
        )
        payloads.extend(_payload(contact) for contact in page.items)
        position += len(page.items)
        if not page.items or not page.has_more:
            break
    return payloads
