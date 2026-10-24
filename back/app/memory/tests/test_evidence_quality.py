"""Durable facts survive near duplicates, delegation and bounded context."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent.contracts import ExecutionResult
from app.dream.mechanisms.task_memory import build_task_extraction_input
from app.memory import acquisition_service, context, service
from app.memory.schemas import MemoryAcquisitionCreate, MemoryItemCreate, MemoryPayload, MemorySimilarityCandidate
from app.task.models import Task, TaskStatus
from app.topic.models import Topic


@pytest.mark.asyncio
@pytest.mark.parametrize("new_fact", [
    "The reporting budget is 900 euros.",
    "The reporting budget is not 800 euros.",
    "The reporting budget is 800 euros except in December.",
    "The reporting budget becomes 900 euros in November.",
])
async def test_similarity_without_equivalence_preserves_the_complete_new_fact(
    db, agents, memory_storage, monkeypatch, new_fact,
):
    owner, _ = agents
    old, _ = await service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Reporting budget", payload=MemoryPayload(text="The reporting budget is 800 euros.")))

    async def candidates(**_kwargs):
        return [[MemorySimilarityCandidate(memory_id=old.id, revision=old.revision,
            title=old.title, excerpt=old.search_text, similarity=0.999)]]

    async def no_decision(**_kwargs):
        return None

    monkeypatch.setattr(acquisition_service, "find_similar_memory_candidates", candidates)
    monkeypatch.setattr(acquisition_service, "run_profile_decision", no_decision)
    result = await acquisition_service.acquire_memory(MemoryAcquisitionCreate(
        agent_id=owner.id, title="Reporting budget change", content=new_fact,
        source_kind="task", source_ref=f"task:{uuid4()}", idempotency_key=f"budget:{uuid4()}",
    ))
    assert result.status == "stored"
    assert result.memory_id != old.id
    _, content, *_ = await service.get_item(result.memory_id, agent_id=owner.id)
    from core.util import visible_text
    assert visible_text(content.decode()) == new_fact
    assert await service.source_refs(old.id) == []


@pytest.mark.parametrize("origin", ["peer", "child", "goal", "prepared"])
def test_task_extraction_preserves_the_source_author(origin):
    task = Task(label="Synthetic prepared work", objective="I prefer weekly reports.",
        status=TaskStatus.SUCCESS, agent_id=7, ai=origin == "peer",
        requester_agent_id=8 if origin == "peer" else None,
        parent_id=uuid4() if origin == "child" else None,
        goal_id=uuid4() if origin == "goal" else None,
        data={"_original_demand": "Please compare reporting options."} if origin == "prepared" else {},
    )
    task.set_execution_result(ExecutionResult(success=True, prompt="Synthetic work", result="The comparison is complete."))
    source = build_task_extraction_input(task, followup=None, topic=Topic(id=uuid4(), title="Reporting", keywords=[]))
    assert all(message.speaker_kind == "AI" or "I prefer weekly" not in message.text for message in source.current)
    if origin == "prepared":
        assert [message.text for message in source.current if message.speaker_kind == "human"] == ["Please compare reporting options."]


def test_causal_task_reference_does_not_turn_a_human_continuation_into_ai():
    task = Task(label="Human continuation", objective="<p>Prepared reporting objective.</p>",
        status=TaskStatus.SUCCESS, agent_id=7, ai=False, requester_user_id=1, source_task_id=uuid4(),
        data={"_original_demand": "I prefer monthly reports."})
    source = build_task_extraction_input(task, followup=None,
        topic=Topic(id=uuid4(), title="Reporting", keywords=[]))
    assert source.current[0].speaker_kind == "human"
    assert source.current[0].text == "I prefer monthly reports."


@pytest.mark.asyncio
async def test_calendar_saturation_keeps_a_relevant_fact_in_the_final_budget(monkeypatch):
    now = datetime.now(timezone.utc)

    def hit(title, text, *, temporal=False):
        return SimpleNamespace(item=SimpleNamespace(id=uuid4(), title=title, temporal={} if temporal else None),
            excerpt=text, score=1.0 if temporal else 0.7, source_refs=[],
            temporal_match_at=now if temporal else None)

    fact = hit("Reporting preference", "Monthly reports must include a cash-flow comparison.")
    calendar = [hit(f"Appointment {index}", "Unrelated scheduled appointment. " * 40, temporal=True) for index in range(4)]

    async def search(*_args, **_kwargs):
        return SimpleNamespace(hits=[fact], has_more=False)

    async def temporal(*_args, **_kwargs):
        return calendar, False

    async def admit(_request, hits):
        return hits

    async def record(**_kwargs):
        pass

    monkeypatch.setattr(context, "search_memory_detailed", search)
    monkeypatch.setattr(context, "temporal_hits", temporal)
    monkeypatch.setattr(context, "admit_recall_hits", admit)
    monkeypatch.setattr(context, "record_llm_retrieval", record)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 4)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 2_000)
    brief = await context.build_memory_brief(agent_id=7, query="monthly reports")
    assert any(item.memory_id == str(fact.item.id) for item in brief.items)
    assert "cash-flow comparison" in brief.rendered
    assert len(brief.items) <= 4 and len(brief.rendered) <= 2_000
    assert brief.truncated


@pytest.mark.asyncio
async def test_conflicting_recall_is_attributed_without_leaking_another_agents_claim(db, agents, memory_storage, monkeypatch):
    from app.memory import retrieval
    from app.memory.embedding import MemoryEmbeddingNotConfiguredError
    from app.memory.models import MemoryLink
    from app.memory.schemas import MemoryRecallRequest

    owner, peer = agents
    memories = []
    for agent, amount in ((owner, "800"), (owner, "900"), (peer, "secret-private")):
        item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agent.id,
            title=f"Reporting budget {amount}", payload=MemoryPayload(text=f"The reporting budget is {amount} euros.")))
        memories.append(item)
        if agent.id == owner.id:
            from app.memory.schemas import MemorySourceCreate
            for index in range(5):
                await service.add_item_source(item.id, MemorySourceCreate(source_kind="manual",
                    source_ref=f"synthetic-budget-source:{item.id}:{index}"), actor_agent_id=owner.id)
    db.add_all([MemoryLink(source_item_id=memories[0].id, target_item_id=other.id,
        relation_type="contradicts", confidence=1.0, suggested=False) for other in memories[1:]])
    await db.flush()

    async def missing():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical recall")

    monkeypatch.setattr(retrieval, "resolve_embedding_model", missing)
    page = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="reporting budget", limit=1))
    assert page.evidence_status == "unassessed"
    assert len(page.hits) == 1 and page.hits[0].conflicts
    other = page.hits[0].conflicts[0]
    assert len(other.source_refs) == 3
    assert other.uri in {f"memory://{item.id}" for item in memories[:2]}
    assert "secret-private" not in page.model_dump_json()
    assert str(memories[2].id) not in page.model_dump_json()
    # With no source left, a dangling conflict must not survive a fresh recall.
    conflict_id = next(item.id for item in memories if f"memory://{item.id}" == other.uri)
    await service.forget_item(conflict_id, actor_agent_id=owner.id)
    refreshed = await retrieval.recall_items(MemoryRecallRequest(agent_id=owner.id, query="reporting budget"))
    assert all(not hit.conflicts for hit in refreshed.hits)


@pytest.mark.asyncio
async def test_repeated_receipts_share_one_origin_and_independent_sources_remain_distinct(db):
    from sqlalchemy import func, select
    from app.memory.provenance import source_origin_expression

    origin = uuid4()
    refs = [f"conversation_round:{origin}", f"conversation_round:{origin}:transcription",
            f"conversation_round:{origin}:analysis", f"conversation_round:{uuid4()}"]
    # Evaluate the real PostgreSQL expression used by ranking, with synthetic rows.
    from sqlalchemy import String, column, values
    sources = values(column("kind", String), column("reference", String)).data(
        [("conversation_round", ref) for ref in refs]).alias("sources")
    count = await db.scalar(select(func.count(func.distinct(source_origin_expression(sources.c.kind, sources.c.reference)))))
    assert count == 2

    from sqlalchemy.dialects.postgresql import JSONB
    same_resource = {"source_evidence": [{"uri": "synthetic://report", "kind": "document_extraction"},
                                         {"uri": "synthetic://report", "kind": "document_interpretation"}]}
    evidence_sources = values(column("kind", String), column("reference", String), column("metadata", JSONB)).data([
        ("conversation_round", refs[0], same_resource),
        ("conversation_round", refs[-1], same_resource),
    ]).alias("evidence_sources")
    assert await db.scalar(select(func.count(func.distinct(source_origin_expression(
        evidence_sources.c.kind, evidence_sources.c.reference, evidence_sources.c.metadata))))) == 1


@pytest.mark.asyncio
async def test_successful_goal_cycles_are_capture_eligible_and_lineage_opt_out_survives_delegation(db, agents, memory_storage):
    from sqlalchemy import select
    from app.document import document_service
    from app.dream.mechanisms.task_memory import task_memory_mechanism
    from app.goal.models import Goal

    owner, _ = agents
    documents = [await document_service.create_document(owner_agent_id=owner.id,
        title=f"Synthetic goal resource {index}", content="<p>Synthetic objective.</p>", task_id=None)
        for index in range(2)]
    goal = Goal(agent_id=owner.id, title="Synthetic durable objective",
        description_document_id=documents[0].id, tracking_document_id=documents[1].id)
    topic = Topic(title="Synthetic goal facts")
    db.add_all([goal, topic])
    await db.flush()
    cycle = Task(agent_id=owner.id, topic_id=topic.id, goal_id=goal.id, status=TaskStatus.SUCCESS,
                 label="Verified goal cycle", objective="<p>A generated cycle instruction.</p>")
    db.add(cycle)
    await db.flush()
    child = Task(agent_id=owner.id, topic_id=topic.id, source_task_id=cycle.id, status=TaskStatus.SUCCESS,
                 label="Verified delegated work", objective="<p>A generated delegated instruction.</p>")
    db.add(child)
    await db.commit()
    assert await task_memory_mechanism.count_pending() == 2
    cycle.data = {"memory_capture": False}
    await db.commit()
    assert await task_memory_mechanism.count_pending() == 0
    assert await task_memory_mechanism.claim_one() is None
    cycle.soft_delete()
    await db.commit()
    assert await task_memory_mechanism.count_pending() == 0
    assert await task_memory_mechanism.claim_one() is None
    # A second, allowed causal root cannot bypass a refusal on the canonical
    # parent; both factual capture and acquired-document lookup use this rule.
    allowed = Task(agent_id=owner.id, topic_id=topic.id, status=TaskStatus.SUCCESS,
                   label="Independent allowed root", objective="<p>Independent synthetic work.</p>")
    db.add(allowed)
    await db.flush()
    child.parent_id = cycle.id
    child.source_task_id = allowed.id
    await db.commit()
    from app.task.facade import memory_evidence_task_tree
    assert set(await db.scalars(memory_evidence_task_tree(select(Task.id).where(Task.id == allowed.id)))) == {allowed.id}
    assert await task_memory_mechanism.count_pending() == 1
