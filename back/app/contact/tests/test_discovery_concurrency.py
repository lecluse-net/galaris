"""Real concurrent transactions; intentionally independent from rollback fixtures."""

import asyncio
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent import register_contact_discovery
from app.agent.models import Agent, Title
from app.contact import discovery
from app.contact.directory import directory
from app.contact.models import ContactDiscoveryJob
from app.contact.tests.test_discovery import deliver, model_boundary
from app.memory.tests.conftest import memory_storage as memory_storage
from core.database import get_db_session
from core.params import params_service, runtime_settings
from core.user import UserModel


@pytest_asyncio.fixture(autouse=True)
async def capture(committed_database, monkeypatch):
    # Mixing the rollback `db` fixture with committed_database can restore its
    # closed connection factory at teardown and contaminate following tests.
    async with get_db_session():
        await params_service.load_params()
    monkeypatch.setattr(runtime_settings, "CONTACT_CAPTURE_ENABLED", True)
    monkeypatch.setattr(runtime_settings, "LOCALIZATION", "Lyon, France")
    discovery.register_contact_runtime()
    yield
    register_contact_discovery(None)


@pytest.mark.asyncio
@pytest.mark.parametrize("second_value", ["nina@example.org", "+33 7 06 05 04 03"])
async def test_concurrent_workers_use_independent_transactions_without_duplicate_people(
    committed_database, memory_storage, monkeypatch, second_value,
):
    _writer, decider = model_boundary(monkeypatch,
        choose=lambda criteria: next((key for key in criteria if key not in {"ignore", "unresolved", "create"}), "create"))
    async with get_db_session() as session:
        title = Title(label="Synthetic concurrent contact owner", gender="X")
        manager = UserModel(email=f"contact-concurrency-{uuid4().hex}@example.org", hashed_password="unused", is_active=True)
        session.add_all((title, manager))
        await session.flush()
        agent = Agent(title_id=title.id, user_id=manager.id, first_name="Synthetic", last_name="Concurrent", code=uuid4().hex)
        session.add(agent)
        await session.flush()
        agent_id = agent.id
        await session.commit()
        await deliver(agent_id, "Nina Fiction : nina@example.org")
        await deliver(agent_id, "Nina Fiction : " + second_value)
    arrived = 0
    both_prepared = asyncio.Event()
    original = decider.side_effect

    async def synchronized_decision(**kwargs):
        nonlocal arrived
        arrived += 1
        if arrived >= 2:
            both_prepared.set()
        await asyncio.wait_for(both_prepared.wait(), 5)
        return await original(**kwargs)

    decider.side_effect = synchronized_decision

    async def worker():
        async with get_db_session():
            return await discovery.process_contact_discovery()

    assert await asyncio.wait_for(asyncio.gather(worker(), worker()), 15) == [1, 1]
    await worker()
    async with get_db_session() as session:
        contacts = await directory(agent_id)
        assert len(contacts) == 1
        assert contacts[0].identities[0].external_id == "nina@example.org"
        if second_value.startswith("+"):
            assert contacts[0].coordinates.phone_numbers[0].number == "+33706050403"
        jobs = (await session.scalars(select(ContactDiscoveryJob))).all()
        assert len(jobs) == 2 and all(job.status == "success" for job in jobs)
        assert {job.contact_item_id for job in jobs} == {contacts[0].memory_item_id}
