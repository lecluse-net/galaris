"""Durable, leased acquisition of detected coordinates into private contacts."""

import asyncio
from datetime import datetime, timedelta, timezone
import hashlib
import json
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from app.agent import ContactDiscoverySource, register_contact_discovery
from app.llm import llm_correlation_scope, llm_execution_scope
from app.llm.facade import llm_call_accounting
from app.memory import (ContactCoordinates, ContactPhoneNumber, ContactPostalAddress,
    MessengerContactIdentityInput, commit_contact_changes, create_address_book_contact,
    lock_messenger_contact, update_messenger_contact)
from core.database import get_db
from core.params import runtime_settings
from core.util import DetectedContactInfo

from .directory import directory, directory_fingerprint, fingerprint, info_key, known_contact, lock_contact_directory
from .discovery_contracts import ContactDiscoveryPlan, ContactDiscoveryRead, ContactOwnerEvidence
from .discovery_inference import resolve_owner
from .models import ContactDiscoveryJob


_MAX_ATTEMPTS = 5
_LEASE_SECONDS = 300
_EXECUTION_SECONDS = 120


async def enqueue_contact_discovery(source: ContactDiscoverySource) -> None:
    if not runtime_settings.CONTACT_CAPTURE_ENABLED or not source.coordinates:
        return
    # Retain nearby ownership context rather than silently cutting off a late coordinate.
    messages = list(source.messages)
    while len(json.dumps(messages, ensure_ascii=False)) > 32000 and len(messages) > 1:
        messages.pop(0)
    records: list[dict[str, Any]] = []
    current_fingerprint = hashlib.sha256(source.current_text.encode()).hexdigest()
    for info in source.coordinates:
        coordinate = info.model_dump(mode="json")
        key = hashlib.sha256(json.dumps([source.source_kind, source.source_ref,
            current_fingerprint, info_key(info)], ensure_ascii=False).encode()).hexdigest()
        if len(source.current_text) <= 32000:
            current = source.current_text
        else:
            current = source.current_text[max(0, info.start - 8000):info.end + 8000]
        records.append({"id": uuid4(), "agent_id": source.agent_id, "source_kind": source.source_kind,
            "source_ref": source.source_ref, "observation_key": key, "coordinate": coordinate,
            "context": {"history": messages, "current": current}, "status": "pending"})
    for offset in range(0, len(records), 100):
        await get_db().execute(insert(ContactDiscoveryJob).values(records[offset:offset + 100])
            .on_conflict_do_nothing(constraint="uq_contact_discovery_observation"))
    # This small durable enqueue finishes before the router can consume its input.
    await get_db().commit()


def register_contact_runtime() -> None:
    from app.llm.facade import register_inference_output
    from .discovery_contracts import ContactOwnerEvidence

    register_inference_output("galaris.contact.owner/v1", ContactOwnerEvidence)
    register_contact_discovery(enqueue_contact_discovery)


async def _claim() -> tuple[UUID, UUID] | None:
    now = datetime.now(timezone.utc)
    record = await get_db().scalar(select(ContactDiscoveryJob).where(
        ContactDiscoveryJob.attempts < _MAX_ATTEMPTS,
        or_(and_(ContactDiscoveryJob.status.in_(("pending", "retry")), ContactDiscoveryJob.available_at <= now),
            and_(ContactDiscoveryJob.status == "running", ContactDiscoveryJob.lease_expires_at <= now)),
    ).order_by(ContactDiscoveryJob.available_at, ContactDiscoveryJob.created_at, ContactDiscoveryJob.id)
        .with_for_update(skip_locked=True).limit(1))
    if record is None:
        # Exhausted crash leases must become visible errors rather than stuck running work.
        from sqlalchemy import update

        await get_db().execute(update(ContactDiscoveryJob).where(
            ContactDiscoveryJob.status == "running", ContactDiscoveryJob.attempts >= _MAX_ATTEMPTS,
            ContactDiscoveryJob.lease_expires_at <= now,
        ).values(status="error", lease_token=None, lease_expires_at=None,
                 last_error="Contact attempt budget exhausted after lease recovery."))
        await get_db().commit()
        return None
    token = uuid4()
    record.status, record.lease_token = "running", token
    record.attempts += 1
    record.lease_expires_at = now + timedelta(seconds=_LEASE_SECONDS)
    identity = record.id
    await get_db().commit()
    return identity, token


async def _owned(identity: UUID, token: UUID) -> ContactDiscoveryJob:
    record = await get_db().scalar(select(ContactDiscoveryJob).where(
        ContactDiscoveryJob.id == identity, ContactDiscoveryJob.status == "running",
        ContactDiscoveryJob.lease_token == token,
        ContactDiscoveryJob.lease_expires_at > datetime.now(timezone.utc),
    ).with_for_update().execution_options(populate_existing=True))
    if record is None:
        raise RuntimeError("Contact discovery lease was lost.")
    return record


async def _apply(identity: UUID, token: UUID, plan: ContactDiscoveryPlan) -> None:
    # One writer per agent serializes duplicate creation, including different messages.
    agent_id = await get_db().scalar(select(ContactDiscoveryJob.agent_id).where(ContactDiscoveryJob.id == identity))
    if agent_id is None:
        raise RuntimeError("Contact discovery job disappeared.")
    await lock_contact_directory(agent_id)
    record = await _owned(identity, token)
    if not runtime_settings.CONTACT_CAPTURE_ENABLED:
        record.status, record.lease_token, record.lease_expires_at = "retry", None, None
        await get_db().commit()
        return
    info = DetectedContactInfo.model_validate(record.coordinate)
    if info.type == "instant_messaging" and not info.platform and plan.owner is not None:
        info = info.model_copy(update={"platform": plan.owner.messaging_platform})
    if info.type == "instant_messaging" and info.platform:
        info = info.model_copy(update={"normalized_value": info_key(info)[2]})
    contacts = await directory(record.agent_id)
    known = known_contact(contacts, info)
    target = known.memory_item_id if known else None
    changed = False
    if known is not None:
        record.status = "success"
    elif plan.action in {"ignore", "unresolved"}:
        record.status = "ignored" if plan.action == "ignore" else "unresolved"
    elif plan.action == "known":
        # A once-known coordinate was removed while this work was waiting.
        record.prepared = None
        record.status = "retry"
    else:
        if plan.owner is None or plan.owner.status != "identified":
            raise ValueError("A supported owner is required before writing a contact.")
        coordinates = ContactCoordinates()
        identities: tuple[MessengerContactIdentityInput, ...] = ()
        if info.type == "phone":
            coordinates = ContactCoordinates(phone_numbers=[ContactPhoneNumber(
                number=info.normalized_value, country=info.country or "")])
        elif info.type == "postal_address":
            coordinates = ContactCoordinates(postal_addresses=[ContactPostalAddress(
                street=info.value, country=info.country or "")])
        elif info.type == "instant_messaging":
            if not info.platform:
                raise ValueError("An instant messaging identity requires its platform.")
            identities = (MessengerContactIdentityInput(kind="messenger", namespace=info.platform,
                external_id=info.normalized_value),)
        if plan.action == "create":
            if directory_fingerprint(contacts) != plan.expected_directory_fingerprint:
                record.prepared, record.status = None, "retry"
                record.lease_token, record.lease_expires_at = None, None
                await get_db().commit()
                return
            contact = await create_address_book_contact(owner_agent_id=record.agent_id,
                display_name=plan.owner.display_name, email=info.normalized_value if info.type == "email" else None,
                coordinates=coordinates, messaging_identities=identities, defer_commit=True)
        else:
            if plan.contact_item_id is None:
                raise ValueError("Enrichment requires a selected contact.")
            contact = await lock_messenger_contact(plan.contact_item_id)
            if contact is None or contact.owner_agent_id != record.agent_id or fingerprint(contact) != plan.expected_contact_fingerprint:
                record.prepared, record.status = None, "retry"
                record.lease_token, record.lease_expires_at = None, None
                await get_db().commit()
                return
            if info.type == "email":
                identities = (MessengerContactIdentityInput(kind="messenger", namespace="mail", external_id=info.normalized_value),)
            combined = tuple(MessengerContactIdentityInput(id=item.id, kind=item.kind,
                namespace=item.namespace, external_id=item.external_id, display_name=item.display_name,
                galaris_user_id=item.galaris_user_id) for item in contact.identities) + identities
            contact = await update_messenger_contact(contact_item_id=contact.memory_item_id,
                display_name=None, coordinates=contact.coordinates.merged_with(coordinates),
                identities=combined if identities else None,
                expected_identities=contact.identities if identities else None, defer_commit=True)
        target, record.status = contact.memory_item_id, "success"
        changed = True
    record.contact_item_id = target
    record.lease_token, record.lease_expires_at, record.last_error = None, None, None
    if target is not None and changed:
        await commit_contact_changes(target)
    else:
        await get_db().commit()


async def process_contact_discovery() -> int:
    """Scheduler callback; its contextual session is supplied by the scheduler root."""
    if not runtime_settings.CONTACT_CAPTURE_ENABLED:
        return 0
    claim = await _claim()
    if claim is None:
        return 0
    identity, token = claim
    try:
        async with asyncio.timeout(_EXECUTION_SECONDS):
            record = await _owned(identity, token)
            info = DetectedContactInfo.model_validate(record.coordinate)
            agent_id, context = record.agent_id, dict(record.context)
            source_kind, source_ref = record.source_kind, record.source_ref
            prepared = dict(record.prepared) if record.prepared is not None else None
            contacts = await directory(agent_id)
            known = known_contact(contacts, info)
            await get_db().commit()
            if known is not None:
                plan, cost = ContactDiscoveryPlan(action="known", contact_item_id=known.memory_item_id), 0.0
            elif prepared is not None and prepared.get("stage") != "owner":
                plan, cost = ContactDiscoveryPlan.model_validate(prepared), 0.0
            else:
                async def checkpoint_owner(owner: ContactOwnerEvidence, cost: float) -> None:
                    checkpoint = await _owned(identity, token)
                    checkpoint.prepared = {"stage": "owner", "owner": owner.model_dump(mode="json")}
                    checkpoint.cost += cost
                    await get_db().commit()

                with (llm_call_accounting(),
                      llm_correlation_scope(f"contact-discovery:{identity}"),
                      llm_execution_scope(source_kind=source_kind, source_id=source_ref,
                                          messenger_origin=source_kind == "conversation_round")):
                    previous_owner = ContactOwnerEvidence.model_validate(prepared["owner"]) if prepared is not None else None
                    plan, cost = await resolve_owner(agent_id=agent_id, info=info, context=context, contacts=contacts,
                        owner=previous_owner, checkpoint_owner=checkpoint_owner)
            record = await _owned(identity, token)
            record.prepared = plan.model_dump(mode="json")
            record.cost += cost
            await get_db().commit()
            await _apply(identity, token, plan)
    except BaseException as exc:
        await get_db().rollback()
        record = await get_db().scalar(select(ContactDiscoveryJob).where(
            ContactDiscoveryJob.id == identity, ContactDiscoveryJob.status == "running",
            ContactDiscoveryJob.lease_token == token,
        ).with_for_update())
        if record is not None:
            interrupted = isinstance(exc, asyncio.CancelledError)
            record.attempts = max(0, record.attempts - int(interrupted))
            record.status = "error" if record.attempts >= _MAX_ATTEMPTS else "retry"
            record.available_at = datetime.now(timezone.utc) + timedelta(seconds=0 if interrupted else 2 ** record.attempts)
            record.lease_token, record.lease_expires_at = None, None
            # Do not persist provider exception bodies containing prompts or transport secrets.
            record.last_error = "Interrupted" if interrupted else type(exc).__name__
            await get_db().commit()
        if isinstance(exc, asyncio.CancelledError):
            raise
        if not isinstance(exc, Exception):
            raise
        logger.warning("Contact discovery {} failed: {}", identity, type(exc).__name__)
    return 1


async def list_contact_discovery(*, agent_id: int, limit: int = 50, offset: int = 0) -> list[ContactDiscoveryRead]:
    rows = (await get_db().scalars(select(ContactDiscoveryJob).where(ContactDiscoveryJob.agent_id == agent_id)
        .order_by(ContactDiscoveryJob.created_at.desc(), ContactDiscoveryJob.id)
        .limit(max(1, min(limit, 500))).offset(max(0, offset)))).all()
    return [ContactDiscoveryRead(id=item.id, agent_id=item.agent_id, status=item.status,
        coordinate=item.coordinate, contact_item_id=item.contact_item_id, attempts=item.attempts,
        last_error=item.last_error) for item in rows]


async def cancel_contact_discovery(contact_item_id: UUID) -> None:
    """Forgetting a contact also prevents queued old observations from recreating it."""
    from app.memory import get_messenger_contact
    from .directory import coordinate_keys

    contact = await get_messenger_contact(contact_item_id)
    if contact is None:
        return
    keys = set(coordinate_keys(contact))
    rows = (await get_db().scalars(select(ContactDiscoveryJob).where(
        ContactDiscoveryJob.agent_id == contact.owner_agent_id,
        ContactDiscoveryJob.status.in_(("pending", "retry", "running")),
    ).order_by(ContactDiscoveryJob.id).with_for_update())).all()
    for row in rows:
        if info_key(DetectedContactInfo.model_validate(row.coordinate)) in keys:
            row.status, row.lease_token, row.lease_expires_at = "ignored", None, None
