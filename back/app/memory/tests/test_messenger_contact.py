from __future__ import annotations
from core.util.rich_text import convert_to_html

import asyncio
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.memory import (
    MessengerContactObservation,
    observe_messenger_contact,
    service,
)
from app.memory.models import (
    MemoryAutomationJob,
    MemoryContactIdentity,
    MemoryItem,
    MemoryRevision,
)
from app.memory.schemas import MemoryItemUpdate, MemorySearchRequest
from app.messenger import observe_contact
from core.database import get_db, get_db_session
from core.user import UserModel


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
    assert item.memory_type == "social"
    assert item.visibility == "private"
    assert item.read_only
    assert item.source_managed
    assert item.managed_source_kind == "messenger_contact"
    assert item.managed_source_ref is not None
    assert len(item.managed_source_ref) == 64
    assert item.title == "Contact — Aster"
    assert item.filename == (
        f"messenger-contact-{item.managed_source_ref}.md"
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
    assert content.decode("utf-8") == convert_to_html(
        "# Contact Messenger\n"
        "\n"
        "- Nom affiché : Aster\n"
        "- Messagerie : nextcloud_talk\n"
        "- Identifiant utilisateur : astertest\n", "text/markdown"
    )
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
                memory_types=["social"],
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
async def test_contact_display_name_is_bounded_to_one_safe_markdown_line(
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
    assert "<li>Nom affiché : Alice *administratrice*</li>" in content.decode(
        "utf-8"
    )
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
async def test_concurrent_first_observations_converge_on_one_item(
    memory_storage: Path,
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
        messaging_id="telegram",
        user_id=f"contact-{suffix}",
    )

    async def project() -> UUID:
        async with get_db_session():
            return await observe_messenger_contact(observation)

    first_id, second_id = await asyncio.gather(project(), project())

    assert first_id == second_id
    async with get_db_session():
        assert await get_db().scalar(
            select(func.count(MemoryItem.id)).where(
                MemoryItem.managed_source_kind == "messenger_contact",
                MemoryItem.metadata_["user_id"].astext == observation.user_id,
            )
        ) == 1
        item = await get_db().get(MemoryItem, first_id)
        assert item is not None
        assert item.revision == 1
        source_ref = item.managed_source_ref
        assert source_ref is not None
        await service.forget_source_managed_item(
            source_kind="messenger_contact",
            source_ref=source_ref,
            item_id=item.id,
        )
        await get_db().execute(
            delete(MemoryAutomationJob).where(
                MemoryAutomationJob.payload["item_id"].astext == str(item.id)
            )
        )
        await get_db().execute(
            delete(MemoryItem).where(MemoryItem.id == item.id)
        )
        await get_db().execute(delete(Agent).where(Agent.id == owner_id))
        await get_db().execute(delete(Title).where(Title.id == title.id))
        await get_db().execute(delete(UserModel).where(UserModel.id == manager.id))
