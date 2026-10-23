"""Recent-memory isolation; document-library workflows live in app.document/tests."""
from pathlib import Path
import pytest
from app.agent import Agent
from app.memory import service
from app.memory.router import read_recent_memories
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from core.authorize import Privileges
from app.document import resource_service as documents
from app.document.schemas import DocumentItemCreate, DocumentPayload, DocumentGrantUpdate

@pytest.mark.asyncio
async def test_recent_memories_respect_management_scope_and_hide_documents(
    agents: tuple[Agent, Agent],
    memory_storage: Path,
) -> None:
    del memory_storage
    managed, peer = agents
    owned, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=managed.id,
            title="Recent owned memory",
            payload=MemoryPayload(text="Owned"),
        )
    )
    shared, _created = await documents.create_item(
        DocumentItemCreate(
            owner_agent_id=peer.id,
            title="Recent shared memory",
            payload=DocumentPayload(text="Shared"),
            node_kind="document",
        )
    )
    hidden, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=peer.id,
            title="Hidden peer memory",
            payload=MemoryPayload(text="Hidden"),
        )
    )
    document, _created = await documents.create_item(
        DocumentItemCreate(
            owner_agent_id=managed.id,
            title="Recent document",
            payload=DocumentPayload(text="Document"),
            node_kind="document",
        )
    )
    await documents.set_item_grant(
        shared.id,
        managed.id,
        DocumentGrantUpdate(can_write=False),
        actor_agent_id=peer.id,
    )

    recent = await service.list_recent_memories(
        managed_agent_ids=frozenset({managed.id}),
        limit=50,
    )
    ids = {item.id for item in recent}

    assert owned.id in ids
    # Shared knowledge is now documentary; the recent-memory list remains private.
    assert shared.id not in ids
    assert hidden.id not in ids
    assert document.id not in ids


def test_recent_memories_require_a_memory_privilege() -> None:
    assert read_recent_memories._authorize_meta[  # pyright: ignore[reportFunctionMemberAccess]
        "privileges"
    ] == [
        Privileges.MEMORY_ACCESS,
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
