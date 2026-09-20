from uuid import uuid4

import pytest
from sqlalchemy import select

from core.dbadmin import SchemaTransitionSet
from app.memory import service
from app.memory.html_migration import (
    convert_html_batch,
    html_conversion_complete,
    needs_html_conversion,
)
from app.memory.models import MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.memory.storage import get_storage


def test_html_action_is_triggered_only_by_its_owned_schema_delta():
    assert not needs_html_conversion(SchemaTransitionSet())
    assert not needs_html_conversion(
        SchemaTransitionSet(added_columns=frozenset({"skills.content"}))
    )
    assert needs_html_conversion(
        SchemaTransitionSet(added_columns=frozenset({"memory_items.content_profile_version"}))
    )


@pytest.mark.asyncio
async def test_conversion_preserves_source_revision_acl_and_replays(db, agents, memory_storage):
    owner, _ = agents
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id, title="Legacy", payload=MemoryPayload(text="Initial")
        )
    )
    provider = get_storage(item.provider_code)
    source = "# Titre\n\nDu **texte** et `<p>`."
    source_resource = await provider.create(source.encode())
    item.resource_id = source_resource
    item.media_type = "text/markdown"
    item.content_profile_version = None
    initial = await db.scalar(
        select(MemoryRevision).where(
            MemoryRevision.item_id == item.id, MemoryRevision.revision == 1
        )
    )
    initial.resource_id = source_resource
    initial.media_type = "text/markdown"
    initial.content_profile_version = None
    await db.flush()
    transitions = SchemaTransitionSet()
    await convert_html_batch(db, transitions)
    assert await html_conversion_complete(db, transitions)
    assert item.revision == 2
    assert item.owner_agent_id == owner.id
    assert item.media_type == "text/html"
    assert await provider.read(source_resource) == source.encode()
    converted_resource = item.resource_id
    assert b"<strong>texte</strong>" in await provider.read(converted_resource)
    await convert_html_batch(db, transitions)
    assert item.revision == 2
    assert item.resource_id == converted_resource
    assert initial.media_type == "text/markdown"


@pytest.mark.asyncio
async def test_native_resources_are_excluded_and_legacy_images_reported(db, agents, memory_storage):
    owner, _ = agents
    native, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id,
            title="JSON",
            content_type="json",
            media_type="application/json",
            payload=MemoryPayload(text='{"native": true}'),
        )
    )
    item, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner.id, title="Legacy image", payload=MemoryPayload(text=str(uuid4()))
        )
    )
    item.resource_id = await get_storage(item.provider_code).create(
        b"![Remote](https://example.invalid/image.png)"
    )
    item.media_type = "text/markdown"
    item.content_profile_version = None
    await db.flush()
    await convert_html_batch(db, SchemaTransitionSet())
    assert not await html_conversion_complete(db, SchemaTransitionSet())
    assert item.media_type == "text/markdown"
    assert item.revision == 1
    assert native.media_type == "application/json"
    assert native.revision == 1
