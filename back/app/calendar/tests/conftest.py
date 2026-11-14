"""Synthetic calendar identities and personal agenda fixtures."""
import pytest_asyncio
from sqlalchemy import select
from app.agent.models import Agent, Title
from app.connection import Connection
from app.services import sync_integrated_service_connections
from app.services.models import Service
from app.calendar import service
from tests.protocol_tools import protocol_tool


@pytest_asyncio.fixture
async def agent(db):
    title = Title(label="Synthetic", gender="M")
    db.add(title)
    await db.flush()
    row = Agent(title_id=title.id, first_name="Synthetic", last_name="Agenda", code="synthetic-calendar-agent")
    db.add(row)
    await db.commit()
    return row


@pytest_asyncio.fixture
async def calendar_connection(db, agent):
    tool = await protocol_tool(db, "calendar")
    row = Connection(service_id=tool.id, agent_id=agent.id, active=True)
    db.add(row)
    await db.commit()
    return row


@pytest_asyncio.fixture
async def personal(db, agent):
    await sync_integrated_service_connections(agent.id)
    connection = (await db.scalars(select(Connection).join(Service, Service.id == Connection.service_id)
        .where(Connection.agent_id == agent.id, Service.code == "agenda"))).one()
    calendar = (await service.list_feeds(connection_id=connection.id))[0]
    return connection, await service.get_feed(calendar.id)
