import pytest_asyncio
from sqlalchemy import select

from app.connection.facade import get_or_create_connection
from app.services import ServiceModel
from app.memory.tests.conftest import agents as agents, memory_storage as memory_storage
from .revision_helpers import revision_clock as revision_clock


@pytest_asyncio.fixture
async def document_tool_agents(db, agents):
    service_id = await db.scalar(select(ServiceModel.id).where(ServiceModel.code == "document"))
    for agent in agents:
        await get_or_create_connection(service_id, agent.id, active=True, commit=False)
    return agents
