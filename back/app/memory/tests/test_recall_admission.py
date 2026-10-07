"""A concurrent committed change must not resurrect a cached search result."""

import asyncio
import builtins
from dataclasses import replace
from uuid import uuid4
from weakref import WeakValueDictionary

import pytest
from sqlalchemy.sql import selectable

from app.agent.models import Agent, Title
from app.memory import bootstrap, context, retrieval, semantic_index, service
from app.agent.context import build_agent_run_context, register_context_provider, unregister_context_provider
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.memory.embedding import EmbeddingModel, MemoryEmbeddingNotConfiguredError
from app.memory.schemas import (
    MemoryGrantUpdate, MemoryItemCreate, MemoryItemUpdate, MemoryPayload,
    MemoryRecallRequest,
)
from core.database import get_db, get_db_session
from core.user import UserModel


@pytest.mark.asyncio
async def test_recall_preserves_access_when_sqlalchemy_reuses_anonymous_names(
    agents, memory_storage, monkeypatch,
):
    owner, reader = agents
    own, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=reader.id, title="Synthetic evidence — owned",
        payload=MemoryPayload(text="<p>Synthetic evidence about the workshop.</p>"),
        media_type="text/html",
    ))
    shared, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Synthetic evidence — shared",
        payload=MemoryPayload(text="<p>Synthetic evidence about the meeting.</p>"),
        media_type="text/html",
    ))
    private, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Synthetic evidence — private",
        payload=MemoryPayload(text="<p>Synthetic evidence reserved for its owner.</p>"),
        media_type="text/html",
    ))
    await service.set_item_grant(shared.id, reader.id, MemoryGrantUpdate(), actor_agent_id=owner.id)

    async def no_embedding():
        raise MemoryEmbeddingNotConfiguredError("unset")
    monkeypatch.setattr(retrieval, "resolve_embedding_model", no_embedding)
    # Reuse an address only once its original CTE is released, as a real
    # allocator can. Generative prefix_with() copies keep the old label after
    # releasing its seed object. Live CTEs must still have distinct addresses.
    allocated = WeakValueDictionary()
    def recycled_id(obj):
        if not isinstance(obj, selectable.CTE):
            return builtins.id(obj)
        for address, live in allocated.items():
            if live is obj:
                return address
        address = 101
        while address in allocated:
            address += 1
        allocated[address] = obj
        return address
    with monkeypatch.context() as allocator:
        allocator.setattr(selectable, "id", recycled_id, raising=False)
        result = await retrieval.recall_items(MemoryRecallRequest(
            agent_id=reader.id, query="Synthetic evidence", limit=8,
        ))
    assert {hit.item.id for hit in result.hits} == {own.id, shared.id}
    assert private.id not in {hit.item.id for hit in result.hits}


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["revoke", "correct", "forget"])
@pytest.mark.parametrize("surface", ["search", "context", "semantic", "frozen"])
async def test_lexical_fallback_admits_only_current_readable_content(
    committed_database, memory_storage, monkeypatch, change, surface,
):
    async with get_db_session() as db:
        user = UserModel(email="recall@example.test", hashed_password="unused", language="fr", is_active=True)
        title = Title(label="Test", gender="X")
        db.add_all([user, title])
        await db.flush()
        agents = [Agent(title_id=title.id, first_name=name, last_name="Recall", code=name,
                        user_id=user.id, agent_driver="internal") for name in ("owner", "reader")]
        db.add_all(agents)
        await db.flush()
        owner_id, reader_id = (agent.id for agent in agents)
        item, _ = await service.create_item(MemoryItemCreate(
            owner_agent_id=owner_id, title="Deployment secret",
            payload=MemoryPayload(text="Deployment uses obsolete credentials."),
        ))
        item_id = item.id
        await service.set_item_grant(item_id, reader_id, MemoryGrantUpdate(), actor_agent_id=owner_id)

    async def mutate():
        async with get_db_session():
            if change == "revoke":
                await service.remove_item_grant(item_id, reader_id, actor_agent_id=owner_id)
            elif change == "correct":
                await service.update_item(item_id, MemoryItemUpdate(
                    payload=MemoryPayload(text="Deployment uses rotated credentials."),
                ), actor_agent_id=owner_id)
            else:
                await service.forget_item(item_id, actor_agent_id=owner_id)

    calls = 0
    async def unavailable_model():
        nonlocal calls
        calls += 1
        # A distinct task/session commits while recall retains its lexical page.
        if calls == (1 if surface == "search" else 2):
            await asyncio.wait_for(asyncio.create_task(mutate()), timeout=15)
        raise MemoryEmbeddingNotConfiguredError("not configured")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", unavailable_model)
    if surface == "semantic":
        model = EmbeddingModel(key="race", code="race", model_name="race", base_url="http://unused.invalid", api_key=None)
        async def resolve():
            return model
        async def embed(texts, **kwargs):
            return [[1.0, 0.0] for _ in texts]
        async def query(*args, **kwargs):
            return [1.0, 0.0]
        monkeypatch.setattr(semantic_index, "resolve_embedding_model", resolve)
        monkeypatch.setattr(semantic_index, "embed_many", embed)
        monkeypatch.setattr(retrieval, "resolve_embedding_model", resolve)
        monkeypatch.setattr(retrieval, "embed_query", query)
        await semantic_index.process_embedding_job({"item_id": str(item_id)})

        class DatabaseBoundary:
            def __getattr__(self, name):
                return getattr(get_db(), name)
            async def execute(self, statement, *args, **kwargs):
                nonlocal calls
                result = await get_db().execute(statement, *args, **kwargs)
                if " AS item_row" in str(statement) and calls == 0:
                    calls += 1
                    await asyncio.wait_for(asyncio.create_task(mutate()), timeout=15)
                return result
        monkeypatch.setattr(retrieval, "get_db", DatabaseBoundary)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    async with get_db_session():
        if surface == "frozen":
            register_context_provider("long_term_memory", bootstrap.memory_context_provider,
                                      refreshes_frozen_kinds=frozenset({"memory"}))
            request = AgentContextRequest(task_id=None, objective="Deployment secret",
                contact_memory_item_id=uuid4(), agent=AgentSnapshot(id=reader_id, code="reader",
                    first_name="Reader", last_name="Recall", driver_code="internal"))
            try:
                first = await build_agent_run_context(request)
                assert "obsolete credentials" in first.shared_context
                # Distinct consumptions commit their exposure observations.
                await get_db().commit()
                second = await build_agent_run_context(replace(request,
                    frozen_capsule=first.context_capsule.model_dump(mode="json")))
                assert "obsolete credentials" not in second.shared_context
                if change != "correct":
                    assert str(item_id) not in second.shared_context
                assert calls == 2
            finally:
                register_context_provider("long_term_memory", bootstrap.memory_context_provider, priority=20,
                                          refreshes_frozen_kinds=frozenset({"memory"}))
            return
        if surface == "context":
            brief = await context.build_memory_brief(agent_id=reader_id, query="Deployment", include_experience=True)
            assert "obsolete credentials" not in brief.rendered
            if change != "correct":
                assert str(item_id) not in brief.rendered
            assert calls == 2
            return
        result = await retrieval.recall_items(MemoryRecallRequest(agent_id=reader_id, query="Deployment"))
    assert all("obsolete credentials" not in hit.excerpt for hit in result.hits)
    if change != "correct":
        assert item_id not in [hit.item.id for hit in result.hits]
    if surface == "semantic":
        assert calls == 1
