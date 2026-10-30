from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.memory import (
    MessengerContactObservation,
    MessengerContactIdentityInput,
    get_messenger_contact,
    merge_messenger_contacts,
    observe_messenger_contact,
    update_messenger_contact,
    create_mail_contact,
    split_messenger_contact,
    service,
)
from app.memory.models import (
    MemoryAutomationJob,
    MemoryContactIdentity,
    MemoryItem,
    MemoryRevision,
)
from app.memory.schemas import MemoryItemCreate, MemoryItemUpdate, MemoryPayload, MemorySearchRequest
from app.messenger import observe_contact
from core.database import get_db, get_db_session
from core.user import UserModel


@pytest.mark.asyncio
@pytest.mark.parametrize("snapshot_change", ["none", "expire", "rollback", "failure"])
async def test_contact_startup_reconciliation_replays_existing_senders_without_implicit_io(
    db, agents, memory_storage, snapshot_change,
):
    from sqlalchemy import event
    from sqlalchemy.exc import IntegrityError
    from app.connection import Connection
    from app.messenger import Message, MessengerUser
    from app.messenger.dbadmin import _reconcile_contacts
    from app.tools import ToolModel

    owner, _ = agents
    owner_id = owner.id
    tool = ToolModel(code="synthetic-contact-backfill", label="Synthetic contact backfill",
        messenger_config={"service": "matrix"}, connection_schema={})
    db.add(tool)
    await db.flush()
    connection = Connection(agent_id=owner_id, tool_id=tool.id, active=True)
    db.add(connection)
    await db.flush()
    connection_id = connection.id
    for index in range(3):
        identity = f"@synthetic-{index}:example.test"
        db.add(MessengerUser(tool_id=tool.id, external_id=identity, display_name=f"Synthetic sender {index}"))
        message = Message(connection_id=connection_id, tool_id=tool.id, platform="matrix",
            user_id=identity, remote_message_id=f"synthetic-inbound-{index}", direction="inbound",
            text="Entirely synthetic content", metadata_={"sender_display_name": f"Synthetic sender {index}"})
        db.add(message)
    await db.commit()
    db.expunge_all()

    def expire_access_snapshots(session):
        # A contact projection may recover from a rollback or refresh the shared
        # session. Reconciliation must not rely on live ORM snapshots across it.
        for instance in tuple(session.identity_map.values()):
            if isinstance(instance, (Connection, ToolModel)):
                session.expire(instance)

    interrupted = False

    class SyntheticProjectionFailure(RuntimeError):
        pass

    def interrupt_identity_flush(session, _context, _instances):
        nonlocal interrupted
        target = MemoryItem if snapshot_change == "failure" else MemoryContactIdentity
        if not interrupted and any(isinstance(instance, target) for instance in session.new):
            interrupted = True
            if snapshot_change == "failure":
                raise SyntheticProjectionFailure("Synthetic projection storage failure")
            raise IntegrityError("Synthetic identity race", None, RuntimeError("Synthetic concurrent insertion"))

    if snapshot_change == "expire":
        event.listen(db.sync_session, "after_commit", expire_access_snapshots)
    elif snapshot_change in {"rollback", "failure"}:
        event.listen(db.sync_session, "before_flush", interrupt_identity_flush)
    try:
        if snapshot_change == "failure":
            with pytest.raises(RuntimeError, match="error_type=SyntheticProjectionFailure"):
                await _reconcile_contacts(db)
        await _reconcile_contacts(db)
        first = (await db.execute(select(Message.id, Message.contact_memory_item_id).where(
            Message.connection_id == connection_id))).all()
        assert len(first) == 3 and all(contact_id is not None for _, contact_id in first)
        await _reconcile_contacts(db)
    finally:
        if snapshot_change == "expire":
            event.remove(db.sync_session, "after_commit", expire_access_snapshots)
        elif snapshot_change in {"rollback", "failure"}:
            event.remove(db.sync_session, "before_flush", interrupt_identity_flush)
            assert interrupted
    assert (await db.execute(select(Message.id, Message.contact_memory_item_id).where(
        Message.connection_id == connection_id))).all() == first


@pytest.mark.asyncio
async def test_address_book_entries_are_independent_private_and_unique(db, agents, memory_storage):
    from app.messenger import MessengerUser

    owner, peer = agents
    counts = [await db.scalar(select(func.count()).select_from(model)) for model in (UserModel, Agent, MessengerUser)]
    record = await create_mail_contact(owner_agent_id=owner.id, display_name="External correspondent", email="OUTSIDE@example.org")
    assert record.display_name == "External correspondent"
    assert [(i.namespace, i.external_id, i.galaris_user_id) for i in record.identities] == [("mail", "outside@example.org", None)]
    assert counts == [await db.scalar(select(func.count()).select_from(model)) for model in (UserModel, Agent, MessengerUser)]
    with pytest.raises(service.MemoryConflictError):
        await create_mail_contact(owner_agent_id=owner.id, display_name="Duplicate", email="outside@example.org")
    independent = await create_mail_contact(owner_agent_id=peer.id, display_name="Private peer", email="outside@example.org")
    assert independent.memory_item_id != record.memory_item_id
    assert await observe_messenger_contact(_observation(owner.id, messaging_id="mail",
        user_id="outside@example.org", display_name="Remote rename")) == record.memory_item_id
    assert (await get_messenger_contact(record.memory_item_id)).display_name == "External correspondent"


@pytest.mark.asyncio
async def test_split_preserves_identity_history_and_rolls_back_all_projections_on_failure(db, agents, memory_storage, monkeypatch):
    from app.memory.models import MemoryContactItem

    owner, _peer = agents
    source_id = await observe_messenger_contact(_observation(owner.id))
    mail = await create_mail_contact(owner_agent_id=owner.id, display_name="External alias", email="alias@example.org")
    async def rewire_references(source, target):
        return {}
    source, _counts = await merge_messenger_contacts(source_contact_item_id=mail.memory_item_id,
        target_contact_item_id=source_id, rewire_references=rewire_references)
    memory, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Synthetic historical preference", payload=MemoryPayload(text="Prefers written summaries.")))
    await service.ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=source_id,
        memory_item_id=memory.id, source_kind="task", source_ref=f"task:{uuid4()}")
    await db.commit()
    selected = next(i for i in source.identities if i.namespace == "mail")
    owner_id = owner.id
    memory_id = memory.id
    original_ids = tuple(i.id for i in source.identities)
    count_before = await db.scalar(select(func.count()).select_from(MemoryItem))
    projection = await db.get(MemoryItem, source_id)
    revision_before = projection.revision
    upsert = service.upsert_source_managed_item
    calls = 0
    async def fail_second_write(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("Synthetic projection failure")
        return await upsert(*args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(service, "upsert_source_managed_item", fail_second_write)
        with pytest.raises(RuntimeError, match="Synthetic projection failure"):
            await split_messenger_contact(contact_item_id=source_id, identity_ids=(selected.id,),
                expected_identity_ids=original_ids, display_name="Single canonical name")
    assert calls == 2
    assert await db.scalar(select(func.count()).select_from(MemoryItem)) == count_before
    assert {i.id for i in (await get_messenger_contact(source_id)).identities} == set(original_ids)
    await db.refresh(projection)
    assert projection.revision == revision_before
    result = await split_messenger_contact(contact_item_id=source_id, identity_ids=(selected.id,),
        expected_identity_ids=original_ids, display_name="Single canonical name")
    assert result.display_name == "Single canonical name"
    assert selected.id not in {i.id for i in result.identities}
    target_id = await db.scalar(select(MemoryContactIdentity.contact_item_id).where(MemoryContactIdentity.id == selected.id))
    target = await get_messenger_contact(target_id)
    assert target.identities == (selected,)
    assert target.linked_memory_count == 0
    assert await db.scalar(select(MemoryContactItem.contact_item_id).where(MemoryContactItem.item_id == memory_id)) == source_id
    assert await observe_messenger_contact(_observation(owner_id, messaging_id="mail", user_id="alias@example.org")) == target_id
    assert await observe_messenger_contact(_observation(owner_id)) == source_id


def _observation(
    owner_agent_id: int,
    *,
    messaging_id: str = "nextcloud_talk",
    user_id: str = "astertest",
    display_name: str = "Aster",
) -> MessengerContactObservation:
    return MessengerContactObservation(
        owner_agent_id=owner_agent_id,
        messaging_id=messaging_id,
        user_id=user_id,
        display_name=display_name,
    )


@pytest.mark.asyncio
async def test_contact_content_is_live_json_without_stored_payload(db, agents, memory_storage):
    from core.storage import get_storage

    owner_id, peer_id = agents[0].id, agents[1].id
    contact_id = await observe_messenger_contact(_observation(owner_id))
    item, content, _access, content_type, media_type = await service.get_item(contact_id, agent_id=owner_id)
    assert item.content is None
    assert all(revision.content is None for revision in item.revisions)
    assert (content_type, media_type) == ("text", "application/json")
    payload = json.loads(content)
    assert payload["display_name"] == "Aster"
    assert payload["identities"][0]["external_id"] == "astertest"
    pointer = item.resource_id
    revision = item.revision
    await observe_messenger_contact(_observation(owner_id, display_name="Synthetic renamed contact"))
    # Change the canonical data without refreshing a generated Memory body.
    await db.execute(update(MemoryContactIdentity).where(
        MemoryContactIdentity.contact_item_id == contact_id,
    ).values(display_name="Synthetic live name", external_id="synthetic-live-address").execution_options(synchronize_session=False))
    await db.execute(update(MemoryItem).where(MemoryItem.id == contact_id).values(metadata_={
        **dict(item.metadata_), "coordinates": {"phone_numbers": [{"number": "+33 1 23 45 67 89"}]},
    }).execution_options(synchronize_session=False))
    await db.commit()
    loaded, current, *_ = await service.get_item(contact_id, agent_id=owner_id, revision=revision)
    current_payload = json.loads(current)
    assert current_payload["display_name"] == "Synthetic live name"
    assert current_payload["identities"][0]["external_id"] == "synthetic-live-address"
    assert current_payload["coordinates"]["phone_numbers"][0]["number"] == "+33 1 23 45 67 89"
    assert loaded.revision == revision + 1
    assert loaded.content is None
    assert await get_storage("native").read(pointer) == current
    with pytest.raises(service.MemoryPermissionError):
        await service.get_item(contact_id, agent_id=peer_id)
    assert not [path for path in memory_storage.rglob("*") if path.is_file()]


@pytest.mark.asyncio
async def test_contact_cleanup_is_idempotent_and_inline_migration_does_not_restore_bodies(db, agents, memory_storage):
    from core.dbadmin import SchemaTransitionSet
    from core.storage import get_storage
    from app.memory.dbadmin import _reconcile_live_contacts
    from app.memory.content_migration import inline_content_complete, migrate_inline_content

    owner_id = agents[0].id
    contact_id = await observe_messenger_contact(_observation(owner_id))
    ordinary, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner_id,
        title="Synthetic retained note", media_type="text/html", payload=MemoryPayload(text="<p>Retained ordinary memory.</p>")))
    ordinary_id = ordinary.id
    legacy = "<p>Synthetic obsolete contact body.</p>"
    await db.execute(update(MemoryItem).where(MemoryItem.id == contact_id).values(
        memory_content=legacy, memory_content_type="text", memory_media_type="text/html"))
    old_pointer = str(uuid4())
    await db.execute(update(MemoryRevision).where(MemoryRevision.item_id == contact_id).values(content=legacy, resource_id=old_pointer))
    await db.commit()
    await migrate_inline_content(db, SchemaTransitionSet())
    # A retained migration backup must not require these generated bodies to
    # reappear after cleanup, or overwrite their canonical metadata/identities.
    await db.execute(text(
        "INSERT INTO galaris_migration.memory_text_contents "
        "(table_name, row_key, resource_ref, content, sha256, size_bytes) "
        "SELECT 'memory_items', id, resource_id, :body, :digest, CAST(:size AS bigint) FROM memory_items WHERE id=:id "
        "UNION ALL SELECT 'memory_revisions', id, resource_id, :body, :digest, CAST(:size AS bigint) "
        "FROM memory_revisions WHERE item_id=:id"
    ), {"id": contact_id, "body": legacy, "digest": hashlib.sha256(legacy.encode()).hexdigest(), "size": len(legacy.encode())})
    await db.commit()
    updated_at = await db.scalar(select(MemoryItem.updated_at).where(MemoryItem.id == contact_id))
    for _ in range(2):
        await _reconcile_live_contacts(db)
        await db.commit()
        await migrate_inline_content(db, SchemaTransitionSet())
        await db.commit()
        assert await inline_content_complete(db, SchemaTransitionSet())
        assert await db.scalar(select(MemoryItem.memory_content).where(MemoryItem.id == contact_id)) is None
        assert not await db.scalar(select(func.count()).select_from(MemoryRevision).where(
            MemoryRevision.item_id == contact_id, MemoryRevision.content.is_not(None)))
        assert await db.scalar(select(MemoryItem.updated_at).where(MemoryItem.id == contact_id)) == updated_at
    db.expire_all()
    _item, content, *_ = await service.get_item(contact_id, agent_id=owner_id, revision=1)
    assert json.loads(content)["identities"][0]["external_id"] == "astertest"
    assert await get_storage("native").read(old_pointer) == content
    assert (await service.get_item(ordinary_id, agent_id=owner_id))[1] == b"<p>Retained ordinary memory.</p>"
    await db.execute(text(
        "UPDATE galaris_migration.memory_text_contents SET sha256=repeat('0', 64) "
        "WHERE table_name='memory_items' AND row_key=:id"
    ), {"id": contact_id})
    assert not await inline_content_complete(db, SchemaTransitionSet())
    await db.rollback()


@pytest.mark.asyncio
async def test_contact_projection_is_private_searchable_idempotent_and_renamable(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    observation = _observation(owner.id)

    item_id = await observe_messenger_contact(observation)
    item = await db.get(MemoryItem, item_id)
    assert item is not None
    assert item.visibility == "private"
    assert item.read_only
    assert item.source_managed
    assert item.managed_source_kind == "messenger_contact"
    assert item.managed_source_ref is not None
    assert len(item.managed_source_ref) == 64
    assert item.title == "Contact — Aster"
    assert item.filename == (
        f"messenger-contact-{item.managed_source_ref}.json"
    )
    assert item.keywords == [
        "contact",
        "messenger",
        "messaging:nextcloud_talk",
        "user:astertest",
        "Aster",
    ]
    assert item.metadata_ == {
        "projection_version": 1,
        "source_kind": "messenger_contact",
        "messaging_id": "nextcloud_talk",
        "user_id": "astertest",
        "display_name": "Aster",
        "memory_filename": item.filename,
    }
    identities = list(
        (
            await db.scalars(
                select(MemoryContactIdentity).where(
                    MemoryContactIdentity.contact_item_id == item_id
                )
            )
        ).all()
    )
    assert [
        (identity.identity_kind, identity.namespace, identity.external_id)
        for identity in identities
    ] == [("messenger", "nextcloud_talk", "astertest")]
    loaded, content, access, _content_type, _media_type = await service.get_item(
        item_id,
        agent_id=owner.id,
    )
    assert loaded.id == item_id
    assert not access.can_write
    payload = json.loads(content)
    assert payload["display_name"] == "Aster"
    assert [(identity["namespace"], identity["external_id"]) for identity in payload["identities"]] == [("nextcloud_talk", "astertest")]
    assert "connection_id" not in content.decode("utf-8")
    assert "connection_id" not in item.metadata_
    assert "room" not in item.metadata_
    assert "message" not in item.metadata_

    initial_revision = item.revision
    assert await observe_messenger_contact(observation) == item_id
    await db.refresh(item)
    assert item.revision == initial_revision
    assert await db.scalar(
        select(func.count(MemoryRevision.id)).where(
            MemoryRevision.item_id == item_id
        )
    ) == 1

    renamed = _observation(owner.id, display_name="Aster Renommée")
    assert await observe_messenger_contact(renamed) == item_id
    await db.refresh(item)
    assert item.revision == initial_revision + 1
    assert item.metadata_["display_name"] == "Aster Renommée"

    assert await observe_messenger_contact(
        _observation(owner.id, display_name="")
    ) == item_id
    await db.refresh(item)
    assert item.revision == initial_revision + 1
    assert item.metadata_["display_name"] == "Aster Renommée"

    for query in ("Aster Renommée", "nextcloud_talk", "astertest"):
        page = await service.search_items(
            MemorySearchRequest(
                agent_id=owner.id,
                query=query,
            )
        )
        assert [hit.item.id for hit in page.hits] == [item_id]

    with pytest.raises(service.MemoryPermissionError, match="source data"):
        await service.update_item(
            item_id,
            MemoryItemUpdate(title="Modification manuelle interdite"),
            actor_agent_id=owner.id,
        )
    with pytest.raises(service.MemoryPermissionError, match="source data"):
        await service.forget_item(item_id, actor_agent_id=owner.id)


@pytest.mark.asyncio
async def test_contact_manual_name_survives_observation_and_preserves_identity(
    db: AsyncSession, agents: tuple[Agent, Agent], memory_storage: Path,
) -> None:
    owner, peer = agents
    contact_id = await observe_messenger_contact(_observation(owner.id))
    peer_id = await observe_messenger_contact(_observation(peer.id))
    before = await get_messenger_contact(contact_id)
    assert before is not None
    item = await db.get(MemoryItem, contact_id)
    item.metadata_ = {**item.metadata_, "merged_contact_item_ids": [str(uuid4())]}
    await db.commit()
    original_metadata = dict(item.metadata_)

    renamed = await update_messenger_contact(
        contact_item_id=contact_id, display_name="  Aster  Exemple  ",
    )
    assert renamed.display_name == "Aster Exemple"
    assert renamed.identities == before.identities
    assert renamed.memory_item_id == contact_id
    assert renamed.owner_agent_id == owner.id
    await db.refresh(item)
    assert item.title == "Contact — Aster Exemple"
    assert item.metadata_["merged_contact_item_ids"] == original_metadata["merged_contact_item_ids"]
    revision = item.revision
    await update_messenger_contact(contact_item_id=contact_id, display_name="Aster Exemple")
    await db.refresh(item)
    assert item.revision == revision

    assert await observe_messenger_contact(
        _observation(owner.id, display_name="New remote name")
    ) == contact_id
    record = await get_messenger_contact(contact_id)
    assert record.display_name == "Aster Exemple"
    assert record.identities[0].display_name == "New remote name"
    assert (await get_messenger_contact(peer_id)).display_name == "Aster"
    loaded, content, *_ = await service.get_item(contact_id, agent_id=owner.id)
    assert loaded.visibility == "private"
    assert loaded.read_only
    assert "Aster Exemple" in content.decode()
    page = await service.search_items(MemorySearchRequest(agent_id=owner.id, query="Aster Exemple"))
    assert [hit.item.id for hit in page.hits] == [contact_id]


@pytest.mark.asyncio
async def test_manual_identities_are_atomic_isolated_and_not_restored_by_observation(db, agents, memory_storage, monkeypatch):
    owner, peer = agents
    contact_id = await observe_messenger_contact(_observation(owner.id))
    peer_id = await observe_messenger_contact(_observation(peer.id))
    occupied_id = await observe_messenger_contact(_observation(owner.id, user_id="occupied"))
    original = await get_messenger_contact(contact_id)
    human = UserModel(email=f"identity-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.commit()
    memory, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Synthetic linked preference", payload=MemoryPayload(text="Synthetic preference."),
    ))
    await service.ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=contact_id,
        memory_item_id=memory.id, source_kind="synthetic", source_ref="synthetic-contact-identity-edit")
    edited = (
        MessengerContactIdentityInput(id=original.identities[0].id, kind="messenger", namespace="matrix",
            external_id="corrected", display_name="Manual identity name"),
        MessengerContactIdentityInput(kind="messenger", namespace="telegram", external_id="123456", display_name="Telegram alias"),
        MessengerContactIdentityInput(kind="galaris_user", namespace="galaris", external_id=str(human.id), galaris_user_id=human.id),
    )
    updated = await update_messenger_contact(contact_item_id=contact_id, display_name="Manual contact",
        identities=edited, expected_identities=original.identities)
    assert updated.linked_memory_count == 1
    assert {(i.kind, i.namespace, i.external_id) for i in updated.identities} == {
        ("messenger", "matrix", "corrected"), ("messenger", "telegram", "123456"), ("galaris_user", "galaris", str(human.id)),
    }
    assert next(i.id for i in updated.identities if i.namespace == "matrix") == original.identities[0].id
    assert await observe_messenger_contact(_observation(owner.id, messaging_id="matrix", user_id="corrected", display_name="Remote overwrite")) == contact_id
    assert (await get_messenger_contact(contact_id)).identities == updated.identities
    assert (await get_messenger_contact(peer_id)).identities[0].external_id == "astertest"
    _, content, *_ = await service.get_item(contact_id, agent_id=owner.id)
    assert "corrected" in content.decode() and "123456" in content.decode()
    assert "astertest" not in content.decode()
    assert await observe_messenger_contact(_observation(owner.id)) != contact_id
    assert (await get_messenger_contact(contact_id)).identities == updated.identities

    conflicts = [
        (MessengerContactIdentityInput(kind="messenger", namespace="nextcloud_talk", external_id="occupied"),),
        (MessengerContactIdentityInput(id=(await get_messenger_contact(occupied_id)).identities[0].id, kind="messenger", namespace="matrix", external_id="foreign"),),
        (edited[0], edited[0]),
        (MessengerContactIdentityInput(kind="galaris_user", namespace="galaris", external_id="2147483647", galaris_user_id=2147483647),),
    ]
    for identities in conflicts:
        with pytest.raises(service.MemoryConflictError):
            await update_messenger_contact(contact_item_id=contact_id, display_name="Must not persist",
                identities=identities, expected_identities=updated.identities)
        current = await get_messenger_contact(contact_id)
        assert current.display_name == "Manual contact"
        assert current.identities == updated.identities
    with pytest.raises(service.MemoryConflictError, match="changed"):
        await update_messenger_contact(contact_item_id=contact_id, display_name="Stale editor",
            identities=(), expected_identities=original.identities)
    async def rewire_references(source, target):
        return {}
    updated, _ = await merge_messenger_contacts(source_contact_item_id=contact_id,
        target_contact_item_id=occupied_id, rewire_references=rewire_references)
    contact_id = occupied_id
    assert updated.linked_memory_count == 1
    assert await observe_messenger_contact(_observation(owner.id, messaging_id="matrix", user_id="corrected", display_name="Remote after merge")) == contact_id
    assert (await get_messenger_contact(contact_id)).identities == updated.identities
    cleared = await update_messenger_contact(contact_item_id=contact_id, display_name="No identities",
        identities=(), expected_identities=updated.identities)
    assert cleared.identities == ()
    assert cleared.linked_memory_count == 1
    await observe_messenger_contact(_observation(owner.id, messaging_id="matrix", user_id="corrected"))
    assert (await get_messenger_contact(contact_id)).identities == ()
    def unavailable_storage(_code):
        raise RuntimeError("Synthetic storage failure")
    with monkeypatch.context() as patch:
        patch.setattr(service, "get_storage", unavailable_storage)
        with pytest.raises(RuntimeError, match="Synthetic storage failure"):
            await update_messenger_contact(contact_item_id=contact_id, display_name="Must roll back",
                identities=(MessengerContactIdentityInput(kind="messenger", namespace="matrix", external_id="uncommitted"),),
                expected_identities=())
    preserved = await get_messenger_contact(contact_id)
    assert preserved.display_name == "No identities"
    assert preserved.identities == ()


@pytest.mark.asyncio
async def test_contact_projection_identity_is_exact_and_isolated(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, peer = agents
    base_id = await observe_messenger_contact(_observation(owner.id))
    other_messaging_id = await observe_messenger_contact(
        _observation(owner.id, messaging_id="matrix")
    )
    other_case_id = await observe_messenger_contact(
        _observation(owner.id, user_id="Astertest")
    )
    other_owner_id = await observe_messenger_contact(_observation(peer.id))

    assert len(
        {base_id, other_messaging_id, other_case_id, other_owner_id}
    ) == 4
    assert await db.scalar(
        select(func.count(MemoryItem.id)).where(
            MemoryItem.id.in_(
                [base_id, other_messaging_id, other_case_id, other_owner_id]
            )
        )
    ) == 4
    with pytest.raises(service.MemoryPermissionError, match="denied"):
        await service.get_item(other_owner_id, agent_id=owner.id)


@pytest.mark.asyncio
async def test_mail_contact_projection_normalizes_case_without_merging_accounts(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents

    first_id = await observe_contact(
        owner_agent_id=owner.id,
        messaging_id="mail",
        user_id="Alice.Example@Example.ORG",
        display_name="Alice Exemple",
    )
    duplicate_id = await observe_contact(
        owner_agent_id=owner.id,
        messaging_id="mail",
        user_id="alice.example@example.org",
    )
    other_account_id = await observe_contact(
        owner_agent_id=owner.id,
        messaging_id="mail",
        user_id="alice.pro@example.org",
        display_name="Alice Exemple",
    )

    assert first_id is not None
    assert duplicate_id == first_id
    assert other_account_id is not None
    assert other_account_id != first_id
    assert await db.scalar(
        select(func.count(MemoryItem.id)).where(
            MemoryItem.managed_source_kind == "messenger_contact",
            MemoryItem.metadata_["messaging_id"].astext == "mail",
            MemoryItem.metadata_["display_name"].astext == "Alice Exemple",
        )
    ) == 2
    item = await db.get(MemoryItem, first_id)
    assert item is not None
    assert item.metadata_["user_id"] == "alice.example@example.org"


@pytest.mark.asyncio
@pytest.mark.parametrize("internal_first", [True, False])
async def test_internal_chat_uses_only_galaris_contact_identity(db, agents, memory_storage, internal_first):
    owner, peer = agents
    human = UserModel(email=f"native-contact-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    internal = MessengerContactObservation(owner.id, "internal", f"user:{human.id}", "Native human", human.id)
    external = MessengerContactObservation(owner.id, "matrix", "@native-human:example.test", "External human", human.id)
    observations = [internal, external] if internal_first else [external, internal]
    contact_id = await observe_messenger_contact(observations[0])
    assert await observe_messenger_contact(observations[1]) == contact_id
    assert await observe_messenger_contact(internal) == contact_id
    contact = await get_messenger_contact(contact_id)
    assert {(i.kind, i.namespace, i.external_id) for i in contact.identities} == {
        ("galaris_user", "galaris", str(human.id)), ("messenger", "matrix", "@native-human:example.test"),
    }
    other_id = await observe_messenger_contact(MessengerContactObservation(peer.id, "internal", f"user:{human.id}", "Native human", human.id))
    assert other_id != contact_id
    assert [(i.kind, i.external_id) for i in (await get_messenger_contact(other_id)).identities] == [("galaris_user", str(human.id))]
    _, content, *_ = await service.get_item(other_id, agent_id=peer.id)
    assert [(identity["kind"], identity["galaris_user_id"]) for identity in json.loads(content)["identities"]] == [("galaris_user", human.id)]
    assert await observe_messenger_contact(MessengerContactObservation(owner.id, "internal", f"user:{human.id}", "Native human", human.id)) == contact_id


@pytest.mark.asyncio
async def test_native_alias_cleanup_preserves_contacts_references_and_unmatched_addresses(db, agents, memory_storage):
    from app.memory.dbadmin import _reconcile_internal_user_identities
    from app.memory.models import MemoryContactItem

    owner, peer = agents
    human = UserModel(email=f"native-cleanup-{uuid4()}@example.test", hashed_password="unused", is_active=True)
    db.add(human)
    await db.flush()
    contact_id = await observe_messenger_contact(MessengerContactObservation(owner.id, "internal", f"user:{human.id}", "Human", human.id))
    other_id = await observe_messenger_contact(MessengerContactObservation(peer.id, "internal", f"user:{human.id}", "Human", human.id))
    memory, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id, title="Synthetic contact note", payload=MemoryPayload(text="A preserved synthetic note.")))
    await service.ensure_contact_memory_scope(owner_agent_id=owner.id, contact_item_id=contact_id,
        memory_item_id=memory.id, source_kind="synthetic", source_ref="native-cleanup-note")
    # Restore the historical redundant address, including a manually managed list.
    item = await db.get(MemoryItem, contact_id)
    item.metadata_ = {**item.metadata_, "identities_managed": True}
    aliases = [MemoryContactIdentity(owner_agent_id=owner.id, contact_item_id=contact_id,
        identity_kind="messenger", namespace=namespace, external_id=address)
        for namespace, address in [("internal", f"user:{human.id}"), ("internal", "unmapped-legacy"), ("matrix", f"user:{human.id}")]]
    db.add_all(aliases)
    await db.commit()
    duplicate_id = aliases[0].id
    keep_ids = {alias.id for alias in aliases[1:]}
    original_user_id = next(i.id for i in (await get_messenger_contact(contact_id)).identities if i.kind == "galaris_user")
    nested = await db.begin_nested()
    await _reconcile_internal_user_identities(db)
    assert await db.get(MemoryContactIdentity, duplicate_id) is None
    await nested.rollback()
    assert await db.get(MemoryContactIdentity, duplicate_id) is not None
    for _ in range(2):
        await _reconcile_internal_user_identities(db)
        await db.commit()
    after = await get_messenger_contact(contact_id)
    assert {i.id for i in after.identities} == keep_ids | {original_user_id}
    assert after.linked_memory_count == 1
    assert (await db.get(MemoryItem, contact_id)).metadata_["identities_managed"] is True
    assert await db.scalar(select(MemoryContactItem.item_id).where(MemoryContactItem.contact_item_id == contact_id)) == memory.id
    assert (await get_messenger_contact(other_id)).memory_item_id == other_id


@pytest.mark.asyncio
async def test_galaris_user_identity_unifies_multiple_channels(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    user = UserModel(
        email=f"contact-user-{uuid4().hex[:10]}@example.test",
        hashed_password="not-used",
        display_name="Alice Multicanal",
        is_active=True,
    )
    db.add(user)
    await db.flush()

    matrix_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="matrix",
            user_id="@alice:example.test",
            display_name="Alice",
            galaris_user_id=user.id,
        )
    )
    telegram_id = await observe_messenger_contact(
        MessengerContactObservation(
            owner_agent_id=owner.id,
            messaging_id="telegram",
            user_id="123456",
            display_name="Alice T.",
            galaris_user_id=user.id,
        )
    )

    assert telegram_id == matrix_id
    identities = list(
        (
            await db.scalars(
                select(MemoryContactIdentity).where(
                    MemoryContactIdentity.contact_item_id == matrix_id
                )
            )
        ).all()
    )
    assert {
        (identity.identity_kind, identity.namespace, identity.external_id)
        for identity in identities
    } == {
        ("galaris_user", "galaris", str(user.id)),
        ("messenger", "matrix", "@alice:example.test"),
        ("messenger", "telegram", "123456"),
    }


@pytest.mark.asyncio
async def test_contact_display_name_is_bounded_to_one_json_value(
    db: AsyncSession,
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    owner, _peer = agents
    item_id = await observe_messenger_contact(
        _observation(owner.id, display_name="Alice\n*administratrice*")
    )

    item = await db.get(MemoryItem, item_id)
    assert item is not None
    assert item.metadata_["display_name"] == "Alice *administratrice*"
    _item, content, _access, _content_type, _media_type = await service.get_item(
        item_id,
        agent_id=owner.id,
    )
    assert json.loads(content)["display_name"] == "Alice *administratrice*"
    assert "\n*administratrice*" not in content.decode("utf-8")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "observation",
    [
        MessengerContactObservation(0, "matrix", "alice"),
        MessengerContactObservation(1, "", "alice"),
        MessengerContactObservation(1, " matrix ", "alice"),
        MessengerContactObservation(1, "matrix", ""),
        MessengerContactObservation(1, "matrix", " "),
        MessengerContactObservation(1, "m" * 513, "alice"),
        MessengerContactObservation(1, "matrix", "u" * 513),
    ],
)
async def test_contact_projection_rejects_invalid_identity(
    db: AsyncSession,
    observation: MessengerContactObservation,
) -> None:
    del db
    with pytest.raises(ValueError):
        await observe_messenger_contact(observation)


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_count", [0, 2])
@pytest.mark.parametrize("address_book", [False, True])
async def test_concurrent_first_observations_converge_on_one_item(
    memory_storage: Path, retired_count: int, address_book: bool,
) -> None:
    del memory_storage
    suffix = uuid4().hex[:10]
    async with get_db_session() as session:
        manager = UserModel(
            email=f"contact-race-{suffix}@example.test",
            hashed_password="not-used",
            display_name="Contact race manager",
            is_active=True,
        )
        session.add(manager)
        title = Title(label=f"Contact race {suffix}", gender="X")
        session.add(title)
        await session.flush()
        owner = Agent(
            user_id=manager.id,
            title_id=title.id,
            first_name="Concurrent",
            last_name="Contact",
            code=f"contact-race-{suffix}",
            agent_driver="internal",
        )
        session.add(owner)
        await session.flush()
        owner_id = owner.id

    observation = _observation(
        owner_id,
        messaging_id="mail" if address_book else "telegram",
        user_id=f"contact-{suffix}@example.org" if address_book else f"contact-{suffix}",
    )
    retired_ids = []
    for _ in range(retired_count):
        async with get_db_session():
            retired_id = ((await create_mail_contact(owner_agent_id=owner_id,
                display_name="Address book entry", email=observation.user_id)).memory_item_id
                if address_book else await observe_messenger_contact(observation))
            contact = await get_messenger_contact(retired_id)
            await update_messenger_contact(contact_item_id=retired_id, display_name="Detached contact",
                identities=(), expected_identities=contact.identities)
            retired_ids.append(retired_id)

    async def project() -> UUID | None:
        async with get_db_session():
            if address_book:
                try:
                    return (await create_mail_contact(owner_agent_id=owner_id,
                        display_name="Address book entry", email=observation.user_id)).memory_item_id
                except service.MemoryConflictError:
                    return None
            return await observe_messenger_contact(observation)

    first_id, second_id = await asyncio.gather(project(), project())

    if address_book:
        assert (first_id is None) != (second_id is None)
        first_id = first_id or second_id
    else:
        assert first_id == second_id
    assert first_id is not None
    async with get_db_session():
        assert await get_db().scalar(
            select(func.count(MemoryItem.id)).where(
                MemoryItem.managed_source_kind == "messenger_contact",
                MemoryItem.metadata_["user_id"].astext == observation.user_id,
            )
        ) == 1 + retired_count
        item = await get_db().get(MemoryItem, first_id)
        assert item is not None
        assert item.revision == 1
        for item_id in [first_id, *retired_ids]:
            item = await get_db().get(MemoryItem, item_id)
            source_ref = item.managed_source_ref
            assert source_ref is not None
            await service.forget_source_managed_item(
                source_kind="messenger_contact", source_ref=source_ref, item_id=item_id,
            )
            await get_db().execute(delete(MemoryAutomationJob).where(
                MemoryAutomationJob.payload["item_id"].astext == str(item_id)))
            await get_db().execute(delete(MemoryItem).where(MemoryItem.id == item_id))
        await get_db().execute(delete(Agent).where(Agent.id == owner_id))
        await get_db().execute(delete(Title).where(Title.id == title.id))
        await get_db().execute(delete(UserModel).where(UserModel.id == manager.id))
