"""Scoped coordinate comparison shared by acquisition and Dream reconciliation."""

import hashlib
import json
import unicodedata
from collections.abc import Iterator

from app.memory import MessengerContactRecord, list_messenger_contacts
from core.util import DetectedContactInfo, country_from_localization, normalize_contact_coordinate
from .countries import default_country


async def lock_contact_directory(agent_id: int) -> None:
    from sqlalchemy import func, select
    from core.database import get_db

    await get_db().execute(select(func.pg_advisory_xact_lock(38172, agent_id)))


def name_key(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                             if not unicodedata.combining(c)).split())


def snapshot(contact: MessengerContactRecord) -> dict[str, object]:
    return {"id": str(contact.memory_item_id), "name": contact.display_name,
        "identities": [{"kind": item.kind, "platform": item.namespace, "value": item.external_id}
                       for item in contact.identities], "coordinates": contact.coordinates.model_dump()}


def fingerprint(contact: MessengerContactRecord) -> str:
    return hashlib.sha256(json.dumps(snapshot(contact), sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def directory_fingerprint(contacts: list[MessengerContactRecord]) -> str:
    return hashlib.sha256("|".join(sorted(fingerprint(item) for item in contacts)).encode()).hexdigest()


async def directory(agent_id: int) -> list[MessengerContactRecord]:
    contacts: list[MessengerContactRecord] = []
    while True:
        batch, _total = await list_messenger_contacts(owner_agent_id=agent_id, limit=500, offset=len(contacts))
        contacts.extend(batch)
        if len(batch) < 500:
            return contacts


def coordinate_keys(contact: MessengerContactRecord) -> Iterator[tuple[str, str, str]]:
    for item in contact.identities:
        if item.kind != "messenger":
            continue
        kind = "email" if item.namespace == "mail" else "instant_messaging"
        platform = "" if kind == "email" else item.namespace
        try:
            yield kind, platform, normalize_contact_coordinate(kind, item.external_id, platform=platform,
                                                              country=default_country() or None)
        except ValueError:
            continue
    for phone in contact.coordinates.phone_numbers:
        try:
            yield "phone", "", normalize_contact_coordinate("phone", phone.number,
                country=country_from_localization(phone.country) or default_country() or None)
        except ValueError:
            continue
    for address in contact.coordinates.postal_addresses:
        value = ", ".join(part for part in (address.street, address.postal_code, address.city, address.region) if part)
        # Match a full entered address and the literal street block used by automatic capture.
        for raw in {value, address.street} - {""}:
            yield "postal_address", "", normalize_contact_coordinate("postal_address", raw)


def info_key(info: DetectedContactInfo) -> tuple[str, str, str]:
    value = normalize_contact_coordinate(info.type, info.normalized_value,
        country=info.country, platform=info.platform)
    return info.type, info.platform or "", value


def known_contact(contacts: list[MessengerContactRecord], info: DetectedContactInfo) -> MessengerContactRecord | None:
    key = info_key(info)
    return next((contact for contact in contacts if key in set(coordinate_keys(contact))), None)
