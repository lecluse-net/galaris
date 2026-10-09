from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import true

from app.agent import AgentManagementScope
from app.memory import graph_state, router, service, source_access
from app.memory.models import MemoryContextEdge, MemoryContextNode
from app.memory.schemas import MemoryGraphRootsRequest, MemoryItemCreate, MemoryPayload
from core.user import UserModel


async def setup(db, agents):
    owner, peer = agents
    humans = [UserModel(email=f"graph-{uuid4()}@example.test", hashed_password="unused") for _ in range(2)]
    db.add_all(humans)
    await db.flush()
    scopes = [AgentManagementScope(user_id=human.id, agent_ids=frozenset({owner.id})) for human in humans]
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Synthetic graph anchor", payload=MemoryPayload(text="Anchor content"),
    ))
    other, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=peer.id, title="Private peer node", payload=MemoryPayload(text="Peer content"),
    ))
    return owner, peer, scopes, item, other


@pytest.mark.asyncio
async def test_graph_state_is_private_persistent_and_restores_hidden_node_positions(db, agents, memory_storage, monkeypatch):
    owner, peer, scopes, item, other = await setup(db, agents)
    context = graph_state.GraphContext(agent_id=owner.id)
    state = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=0,
        positions={item.id: graph_state.GraphPoint(x=123, y=-456), other.id: graph_state.GraphPoint(x=9, y=9)},
        preferences=graph_state.GraphPreferencesPatch(hidden_entity_kinds=["memory"]),
    ), scopes[0])
    assert state.positions == {item.id: graph_state.GraphPoint(x=123, y=-456)}
    assert (await graph_state.read_state(context, scopes[0])).preferences.hidden_entity_kinds == ["memory"]
    assert (await graph_state.read_state(context, scopes[1])).revision == 0
    assert (await graph_state.read_state(graph_state.GraphContext(agent_id=owner.id, query="Anchor"), scopes[0])).revision == 0
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scopes[0]))
    page = await router.list_memory_graph_roots(MemoryGraphRootsRequest(agent_id=owner.id, include_saved_positions=True))
    assert page.positions == {str(item.id): (123, -456)}
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scopes[1]))
    assert not (await router.list_memory_graph_roots(MemoryGraphRootsRequest(agent_id=owner.id, include_saved_positions=True))).positions
    with pytest.raises(HTTPException) as denied:
        await router.read_memory_graph_state(graph_state.GraphContext(agent_id=peer.id))
    assert denied.value.status_code == 404


@pytest.mark.asyncio
async def test_incremental_save_preserves_other_nodes_and_conflicts_do_not_overwrite(db, agents, memory_storage):
    owner, _, scopes, item, _ = await setup(db, agents)
    context = graph_state.GraphContext(agent_id=owner.id)
    first = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=0, positions={item.id: graph_state.GraphPoint(x=1, y=2)},
        preferences=graph_state.GraphPreferencesPatch(hidden_entity_kinds=["contact"]),
    ), scopes[0])
    with pytest.raises(service.MemoryConflictError):
        await graph_state.write_state(graph_state.GraphStateWrite(
            agent_id=owner.id, expected_revision=0,
            preferences=graph_state.GraphPreferencesPatch(hidden_entity_kinds=[]),
        ), scopes[0])
    second = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=first.revision,
        preferences=graph_state.GraphPreferencesPatch(camera=graph_state.GraphCamera(center=(30, 40), zoom=2)),
    ), scopes[0])
    assert second.preferences.hidden_entity_kinds == ["contact"]
    assert await graph_state.page_positions(context, scopes[0], [item.id]) == {item.id: graph_state.GraphPoint(x=1, y=2)}
    # An independently calculated cold tab must not move the saved anchors.
    third = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=second.revision,
        positions={item.id: graph_state.GraphPoint(x=999, y=999)},
    ), scopes[0])
    assert third.positions[item.id] == graph_state.GraphPoint(x=1, y=2)


@pytest.mark.asyncio
async def test_revoked_nodes_and_expansions_are_not_restored(db, agents, memory_storage, monkeypatch):
    owner, _, scopes, item, _ = await setup(db, agents)
    await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=0, positions={item.id: graph_state.GraphPoint(x=1, y=2)},
        preferences=graph_state.GraphPreferencesPatch(expanded_branches=[item.id]),
    ), scopes[0])
    item.soft_delete()
    await db.commit()
    assert not (await graph_state.read_state(graph_state.GraphContext(agent_id=owner.id), scopes[0])).preferences.expanded_branches
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scopes[0]))
    assert not (await router.list_memory_graph_roots(MemoryGraphRootsRequest(agent_id=owner.id, include_saved_positions=True))).positions


@pytest.mark.parametrize("payload", [{"x": float("nan"), "y": 0}, {"x": 0, "y": float("inf")}])
def test_invalid_coordinates_are_rejected(payload):
    with pytest.raises(ValidationError):
        graph_state.GraphPoint.model_validate(payload)


@pytest.mark.asyncio
async def test_live_source_revocation_blocks_saved_items_and_context_expansions(db, agents, memory_storage, monkeypatch):
    owner, _, scopes, item, _ = await setup(db, agents)
    # Replace the external permission boundary, preserving real DB and graph services.
    monkeypatch.setattr(source_access, "_checks", dict(source_access._checks))
    monkeypatch.setattr(source_access, "_batch_readers", dict(source_access._batch_readers))
    readable = True

    async def source_reader(_identity, _agent):
        return readable

    source_access.register_source_access("synthetic-graph-source", lambda _column: true(), source_reader)
    item.source_managed = True
    item.read_only = True
    item.managed_source_kind = "synthetic-graph-source"
    item.managed_source_ref = "synthetic:graph:permission-boundary"
    context_node = MemoryContextNode(owner_agent_id=owner.id, context_kind="conversation",
                                     context_key="synthetic-graph-context", title="Synthetic conversation")
    db.add(context_node)
    await db.flush()
    db.add(MemoryContextEdge(context_node_id=context_node.id, item_id=item.id))
    await db.commit()
    state = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=0,
        positions={item.id: graph_state.GraphPoint(x=1, y=2), context_node.id: graph_state.GraphPoint(x=3, y=4)},
        preferences=graph_state.GraphPreferencesPatch(expanded_branches=[context_node.id]),
    ), scopes[0])
    assert set(state.positions) == {item.id, context_node.id}
    readable = False
    context = graph_state.GraphContext(agent_id=owner.id)
    assert not (await graph_state.read_state(context, scopes[0])).preferences.expanded_branches
    denied = await graph_state.write_state(graph_state.GraphStateWrite(
        agent_id=owner.id, expected_revision=state.revision,
        positions={item.id: graph_state.GraphPoint(x=5, y=6)},
        preferences=graph_state.GraphPreferencesPatch(expanded_branches=[context_node.id]),
    ), scopes[0])
    assert not denied.positions
    assert not denied.preferences.expanded_branches
    monkeypatch.setattr(router, "current_management_scope", AsyncMock(return_value=scopes[0]))
    page = await router.list_memory_graph_roots(MemoryGraphRootsRequest(agent_id=owner.id, include_saved_positions=True))
    assert str(item.id) not in page.positions
