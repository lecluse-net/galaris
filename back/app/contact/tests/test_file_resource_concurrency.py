"""Concurrent contact file writers use real, independently committed transactions."""

import asyncio
import json
from uuid import uuid4

import pytest

from app.agent.models import Agent, Title
from app.contact.schemas import ContactCreate
from app.contact.service import create_contact
from app.file_share import resource_service as files
from app.file_share.resource_contracts import ResourceContext
from app.file_share.resource_uri import ResourceRevisionConflict
from app.memory.tests.conftest import memory_storage as memory_storage
from core.database import get_db_session
from core.user import UserModel


@pytest.mark.asyncio
async def test_two_contact_file_writers_cannot_overwrite_the_same_snapshot(committed_database, memory_storage):
    async with get_db_session() as session:
        title = Title(label="Synthetic contact file race", gender="X")
        manager = UserModel(email="contact-file-race@example.org", hashed_password="unused", is_active=True)
        session.add_all((title, manager))
        await session.flush()
        owner = Agent(title_id=title.id, user_id=manager.id, first_name="Synthetic", last_name="Concurrent Files", code=uuid4().hex)
        session.add(owner)
        await session.flush()
        contact = await create_contact(ContactCreate(agent_id=owner.id, display_name="Synthetic Original", email="race@example.org"))
        ctx = ResourceContext(agent_id=owner.id, runtime="internal")
        uri = f"galaris://contact/{contact.memory_item_id}"
        original = await files.resource_read(ctx, uri)
        await session.commit()

    async def write(name):
        async with get_db_session() as session:
            result = await files.resource_write(ctx, uri, json.dumps({"display_name": name}).encode(), expected_etag=original.etag)
            await session.commit()
            return result

    results = await asyncio.wait_for(asyncio.gather(write("Synthetic First"), write("Synthetic Second"), return_exceptions=True), 10)
    assert sum(isinstance(result, ResourceRevisionConflict) for result in results) == 1
    assert sum(not isinstance(result, BaseException) for result in results) == 1
    async with get_db_session():
        current = await files.resource_read(ctx, uri)
        assert json.loads(current.content)["display_name"] in {"Synthetic First", "Synthetic Second"}
        assert current.etag != original.etag
