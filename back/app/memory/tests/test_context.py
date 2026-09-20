from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest
from app.agent.context import (
    build_agent_run_context,
    register_context_provider,
    unregister_context_provider,
)
from app.agent.contracts import (
    AgentContextCandidate,
    AgentContextContribution,
    AgentContextRequest,
    AgentSnapshot,
)
from app.memory import bootstrap, context
from app.memory.contracts import MemoryBrief, MemoryContextItem


@pytest.fixture(autouse=True)
def admit_synthetic_context_pages(monkeypatch):
    # This file isolates prompt budgeting with synthetic facade results. Real
    # concurrent admission is covered by test_recall_admission.py.
    async def admit(_agent_id, hits):
        return hits
    monkeypatch.setattr(context, "admit_recall_hits", admit)


def _request(
    *,
    label: str = "",
    objective: str = "Use prior deployment knowledge",
    task_data: dict[str, object] | None = None,
    topic_id: UUID | None = None,
    contact_memory_item_id: UUID | None = None,
    include_historical_context: bool = True,
) -> AgentContextRequest:
    return AgentContextRequest(
        task_id=uuid4(),
        agent=AgentSnapshot(
            id=7,
            code="tester",
            first_name="Test",
            last_name="Agent",
            driver_code="internal",
        ),
        objective=objective,
        label=label,
        task_data=task_data or {},
        message_platform="matrix",
        message_group_id="room-1",
        topic_id=topic_id,
        contact_memory_item_id=contact_memory_item_id,
        include_historical_context=include_historical_context,
        fallback_history=({"role": "user", "text": "fallback"},),
    )


@pytest.mark.asyncio
async def test_context_registry_is_ordered_and_fail_open() -> None:
    async def failing(_request: AgentContextRequest) -> AgentContextContribution:
        raise RuntimeError("provider unavailable")

    register_context_provider(
        "test-second",
        lambda _request: AgentContextContribution(
            shared_context="second",
            conversation_history=({"role": "assistant", "text": "canonical"},),
            messaging_context={"cursor": "2"},
        ),
        priority=902,
    )
    register_context_provider(
        "test-first",
        lambda _request: AgentContextContribution(
            system_instructions="first-system",
            shared_context="first",
            messaging_context={"cursor": "1"},
        ),
        priority=901,
    )
    register_context_provider("test-failure", failing, priority=903)
    try:
        built = await build_agent_run_context(_request())
    finally:
        for name in ("test-first", "test-second", "test-failure"):
            unregister_context_provider(name)

    assert built.system_instructions.endswith("first-system")
    assert built.shared_context.endswith("first\n\nsecond")
    assert built.conversation_history[-1]["text"] == "canonical"
    assert built.messaging_context["cursor"] == "2"
    assert built.metadata["test-failure_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_context_providers_receive_history_resolved_by_earlier_provider() -> None:
    captured: list[tuple[object, ...]] = []

    register_context_provider(
        "test-history-source",
        lambda _request: AgentContextContribution(
            conversation_history=({"role": "assistant", "text": "canonical"},),
        ),
        priority=900,
    )

    def capture(request: AgentContextRequest) -> AgentContextContribution:
        captured.append(tuple(request.available_history))
        return AgentContextContribution()

    register_context_provider("test-history-consumer", capture, priority=901)
    try:
        await build_agent_run_context(_request())
    finally:
        unregister_context_provider("test-history-source")
        unregister_context_provider("test-history-consumer")

    assert captured == [({"role": "assistant", "text": "canonical"},)]


@pytest.mark.asyncio
async def test_standalone_objective_drops_historical_context_but_keeps_live_context() -> None:
    contact_id = uuid4()
    register_context_provider(
        "test-standalone-objective",
        lambda _request: AgentContextContribution(
            system_instructions="current policy",
            shared_context="current working set",
            memory_context="obsolete recalled memory",
            continuity_context="obsolete prior task",
            conversation_history=({"role": "user", "text": "obsolete message"},),
            candidates=(
                AgentContextCandidate(
                    key="memory:obsolete",
                    kind="memory",
                    reference="memory://obsolete",
                    excerpt="obsolete capsule entry",
                ),
            ),
            messaging_context={"participant_id": "nicolas"},
        ),
        priority=900,
    )
    try:
        built = await build_agent_run_context(
            _request(
                contact_memory_item_id=contact_id,
                include_historical_context=False,
            )
        )
    finally:
        unregister_context_provider("test-standalone-objective")

    assert built.system_instructions.endswith("current policy")
    assert built.shared_context.endswith("current working set")
    assert built.messaging_context["participant_id"] == "nicolas"
    assert built.memory_context == ""
    assert built.continuity_context == ""
    assert built.conversation_history == ()
    assert built.context_capsule is None


@pytest.mark.asyncio
async def test_interlocutor_capsule_is_ranked_bounded_and_frozen() -> None:
    contact_id = uuid4()
    older_id = uuid4()
    relevant_id = uuid4()
    register_context_provider(
        "test-capsule",
        lambda _request: AgentContextContribution(
            candidates=(
                AgentContextCandidate(
                    key=f"memory:{older_id}",
                    kind="memory",
                    reference=str(older_id),
                    title="Unrelated holiday",
                    excerpt="A trip unrelated to the deployment.",
                    base_score=0.2,
                ),
                AgentContextCandidate(
                    key=f"resource:{relevant_id}",
                    kind="resource",
                    reference=str(relevant_id),
                    title="Deployment runbook",
                    excerpt="Reuse this exact deployment document.",
                    base_score=0.9,
                ),
            ),
            metadata={
                "memory_context_enabled": True,
                "memory_context_ids": [str(older_id), str(uuid4())],
                "memory_context_count": 2,
                "memory_context_truncated": False,
            },
        ),
        priority=900,
    )
    try:
        first = await build_agent_run_context(
            _request(
                objective="Continue the deployment document",
                contact_memory_item_id=contact_id,
            )
        )
        assert first.context_capsule is not None
        frozen = first.context_capsule.model_dump(mode="json")
        second = await build_agent_run_context(
            replace(
                _request(
                    objective="A completely different request",
                    contact_memory_item_id=contact_id,
                ),
                frozen_capsule=frozen,
            )
        )
    finally:
        unregister_context_provider("test-capsule")

    assert first.context_capsule.entries[0].reference == str(relevant_id)
    assert first.metadata["memory_context_ids"] == [str(older_id)]
    assert first.metadata["memory_context_count"] == 1
    assert first.metadata["memory_context_retrieved_count"] == 2
    assert first.metadata["memory_context_truncated"] is True
    # Freshly admitted Memory may renew the capsule's creation timestamp.
    # Stable source content and the other frozen kinds remain identical.
    assert second.context_capsule.entries == first.context_capsule.entries
    assert second.context_capsule.rendered == first.context_capsule.rendered
    assert str(relevant_id) in second.shared_context
    assert str(older_id) in first.memory_context
    assert str(relevant_id) not in first.memory_context
    assert str(relevant_id) in first.continuity_context
    assert str(older_id) not in first.continuity_context


@pytest.mark.asyncio
async def test_frozen_memory_is_removed_when_its_fresh_provider_fails():
    contact_id = uuid4()
    fail = False
    def provider(_request):
        if fail:
            raise RuntimeError("database temporarily unavailable")
        return AgentContextContribution(candidates=(AgentContextCandidate(
            key="memory:test", kind="memory", reference="old-memory", excerpt="Expired private content",
        ),))
    register_context_provider("fresh-memory-test", provider, refreshes_frozen_kinds=frozenset({"memory"}))
    try:
        first = await build_agent_run_context(_request(contact_memory_item_id=contact_id))
        assert "Expired private content" in first.shared_context
        fail = True
        second = await build_agent_run_context(replace(_request(contact_memory_item_id=contact_id),
            frozen_capsule=first.context_capsule.model_dump(mode="json")))
        assert "Expired private content" not in second.shared_context
        assert second.context_capsule.entries == []
    finally:
        unregister_context_provider("fresh-memory-test")


@pytest.mark.asyncio
async def test_context_capsule_deduplicates_resources_by_canonical_uri() -> None:
    contact_id = uuid4()
    document_id = uuid4()
    reference = f"document://{document_id}"
    register_context_provider(
        "test-resource-deduplication",
        lambda _request: AgentContextContribution(
            candidates=(
                AgentContextCandidate(
                    key=f"conversation-document:{reference}",
                    kind="resource",
                    reference=reference,
                    title="Recent conversation document",
                    excerpt="Last conversation operation: file_read",
                    base_score=0.95,
                    provenance=("galaris://text/round-1",),
                ),
                AgentContextCandidate(
                    key=f"resource:memory_document:{reference}:1",
                    kind="resource",
                    reference=reference,
                    title="Deployment runbook",
                    excerpt="Primary document from the deployment Task.",
                    revision=1,
                    base_score=0.9,
                    provenance=("galaris://task/task-1",),
                ),
            )
        ),
        priority=900,
    )
    try:
        built = await build_agent_run_context(
            _request(
                objective="Read the deployment runbook",
                contact_memory_item_id=contact_id,
            )
        )
    finally:
        unregister_context_provider("test-resource-deduplication")

    assert built.context_capsule is not None
    resources = [
        entry for entry in built.context_capsule.entries if entry.kind == "resource"
    ]
    assert len(resources) == 1
    assert resources[0].reference == reference
    assert resources[0].revision == 1
    assert resources[0].provenance == (
        "galaris://text/round-1",
        "galaris://task/task-1",
    )
    assert built.continuity_context.count(reference) == 1


@pytest.mark.asyncio
async def test_conversation_candidates_do_not_enter_capsule_or_replace_history() -> None:
    contact_id = uuid4()
    register_context_provider(
        "test-conversation-candidate",
        lambda _request: AgentContextContribution(
            candidates=(
                AgentContextCandidate(
                    key="message:old",
                    kind="conversation",
                    reference="old",
                    title="Interlocutor message",
                    excerpt="Old duplicated message",
                    metadata={"message": {"role": "user", "text": "old"}},
                ),
            )
        ),
        priority=900,
    )
    try:
        built = await build_agent_run_context(
            _request(contact_memory_item_id=contact_id)
        )
    finally:
        unregister_context_provider("test-conversation-candidate")

    assert built.conversation_history == ({"role": "user", "text": "fallback"},)
    assert built.context_capsule is not None
    assert built.context_capsule.entries == []
    assert "Old duplicated message" not in built.shared_context


@pytest.mark.asyncio
async def test_memory_brief_has_a_strict_character_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item_id = uuid4()

    async def fake_search(_request: object) -> SimpleNamespace:
        hit = SimpleNamespace(
            item=SimpleNamespace(
                id=item_id,
                title="A long deployment procedure",
                memory_type="procedural",
            ),
            source_refs=["task:1"],
            excerpt="x" * 3_000,
            score=0.9,
        )
        return SimpleNamespace(hits=[hit], has_more=False)

    async def fake_recall(
        text: str,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None = None,
        **kwargs: object,
    ) -> SimpleNamespace:
        assert not record_llm_access
        assert telemetry_kind == "context"
        return await fake_search(SimpleNamespace(query=text, **kwargs))

    recorded: list[tuple[UUID, float]] = []

    async def fake_record_llm_retrieval(
        *,
        agent_id: int,
        item_scores: Sequence[tuple[UUID, float]],
        query: str,
        task_id: UUID | None,
        access_kind: str,
    ) -> None:
        assert agent_id == 7
        assert query == "deployment"
        assert task_id is None
        assert access_kind == "context"
        recorded.extend(item_scores)

    monkeypatch.setattr(context, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(
        context,
        "record_llm_retrieval",
        fake_record_llm_retrieval,
    )
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 2)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 1_000)

    brief = await context.build_memory_brief(agent_id=7, query="deployment")

    assert len(brief.rendered) <= 1_000
    assert brief.truncated
    assert brief.items[0].memory_id == str(item_id)
    assert "consult them before searching memory:// again" in brief.rendered
    assert "source=task:1" in brief.rendered
    assert recorded == [(item_id, 0.9)]


@pytest.mark.asyncio
async def test_memory_brief_ranks_core_with_other_types_and_contact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core_id = uuid4()
    relevant_id = uuid4()
    contact_id = uuid4()

    def hit(
        item_id: UUID,
        *,
        title: str,
        memory_type: str,
        score: float,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            item=SimpleNamespace(
                id=item_id,
                title=title,
                memory_type=memory_type,
            ),
            source_refs=["manual"],
            excerpt=title,
            score=score,
        )

    async def fake_recall(
        text: str,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None = None,
        **kwargs: object,
    ) -> SimpleNamespace:
        assert not record_llm_access
        assert telemetry_kind == "context"
        assert text == "deployment"
        assert kwargs["contact_item_id"] == contact_id
        assert kwargs["strict_contact_scope"] is False
        assert kwargs["exclude_agent_projections"] is True
        assert kwargs["memory_types"] == [
            "core",
            "working",
            "episodic",
            "semantic",
            "procedural",
            "social",
        ]
        return SimpleNamespace(
            hits=[
                hit(
                    relevant_id,
                    title="Deployment procedure",
                    memory_type="procedural",
                    score=0.8,
                ),
                hit(
                    core_id,
                    title="Always address the user in French",
                    memory_type="core",
                    score=0.7,
                ),
            ],
            has_more=False,
        )

    recorded: list[tuple[UUID, float]] = []

    async def fake_record_llm_retrieval(
        *,
        agent_id: int,
        item_scores: Sequence[tuple[UUID, float]],
        query: str,
        task_id: UUID | None,
        access_kind: str,
    ) -> None:
        assert agent_id == 7
        assert query == "deployment"
        assert task_id is None
        assert access_kind == "context"
        recorded.extend(item_scores)

    monkeypatch.setattr(context, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(
        context,
        "record_llm_retrieval",
        fake_record_llm_retrieval,
    )
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 8)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 4_000)

    brief = await context.build_memory_brief(
        agent_id=7,
        query="deployment",
        contact_item_id=contact_id,
    )

    assert [item.memory_id for item in brief.items] == [
        str(relevant_id),
        str(core_id),
    ]
    assert recorded == [(relevant_id, 0.8), (core_id, 0.7)]


@pytest.mark.asyncio
async def test_memory_brief_can_return_no_automatic_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_recall(
        _text: str,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None = None,
        **_kwargs: object,
    ) -> SimpleNamespace:
        assert record_llm_access is False
        assert telemetry_kind == "context"
        return SimpleNamespace(hits=[], has_more=False)

    recorded: list[tuple[UUID, float]] = []

    async def fake_record(**kwargs: object) -> None:
        scores = cast(Sequence[tuple[UUID, float]], kwargs["item_scores"])
        recorded.extend(scores)

    monkeypatch.setattr(context, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(context, "record_llm_retrieval", fake_record)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 8)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 4_000)

    brief = await context.build_memory_brief(agent_id=7, query="deployment")

    assert brief.items == ()
    assert brief.rendered == ""
    assert recorded == []


@pytest.mark.asyncio
async def test_active_context_reserves_experience_slots_and_usage_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    general_ids = [uuid4(), uuid4(), uuid4()]
    experience_ids = [uuid4(), uuid4()]

    def hit(item_id: UUID, *, role: str, score: float) -> SimpleNamespace:
        return SimpleNamespace(
            item=SimpleNamespace(
                id=item_id,
                title=f"Memory {item_id}",
                memory_type="procedural",
                node_kind="memory",
                metadata={
                    "memory_role": role,
                    "applicability": "deployments",
                    "confidence": 0.9,
                    "evidence_count": 3,
                },
            ),
            source_refs=["task:1"],
            excerpt="Apply the verified procedure.",
            score=score,
        )

    async def fake_recall(
        _text: str,
        *,
        record_llm_access: bool,
        telemetry_kind: str | None = None,
        **kwargs: object,
    ) -> SimpleNamespace:
        assert record_llm_access is False
        if kwargs.get("memory_role") == "experience":
            return SimpleNamespace(
                hits=[
                    hit(item_id, role="experience", score=0.95 - index * 0.01)
                    for index, item_id in enumerate(experience_ids)
                ],
                has_more=False,
            )
        return SimpleNamespace(
            hits=[
                hit(item_id, role="ordinary", score=0.8 - index * 0.01)
                for index, item_id in enumerate(general_ids)
            ],
            has_more=False,
        )

    usages: list[tuple[str, list[UUID]]] = []

    async def fake_record(**kwargs: object) -> None:
        scores = cast(Sequence[tuple[UUID, float]], kwargs["item_scores"])
        usages.append(
            (
                str(kwargs["access_kind"]),
                [item_id for item_id, _score in scores],
            )
        )

    monkeypatch.setattr(context, "search_memory_detailed", fake_recall)
    monkeypatch.setattr(context, "record_llm_retrieval", fake_record)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_ITEMS", 3)
    monkeypatch.setattr(context.runtime_settings, "MEMORY_CONTEXT_MAX_CHARS", 4_000)
    monkeypatch.setattr(context.runtime_settings, "DREAM_EXPERIENCE_MAX_ITEMS", 2)
    monkeypatch.setattr(context.runtime_settings, "DREAM_EXPERIENCE_MAX_CHARS", 2_000)

    brief = await context.build_memory_brief(
        agent_id=7,
        query="deployment",
        task_id=uuid4(),
        include_experience=True,
        stage="planning",
    )

    assert [item.memory_id for item in brief.items] == [
        str(general_ids[0]),
        *(str(item_id) for item_id in experience_ids),
    ]
    assert "## Relevant prior experience" in brief.rendered
    assert "applicability=deployments" in brief.rendered
    assert usages == [
        ("context", [general_ids[0]]),
        ("experience_planning", experience_ids),
    ]


def test_memory_context_query_prefers_the_bounded_goal_title() -> None:
    objective = """
You are advancing a long-running Goal through one concrete work cycle.

GOAL TITLE:
Créer et rendre rentable l’entreprise d’ici septembre 2027

DURABLE GOAL TRACKING:
""" + ("A very long tracking document. " * 200)

    query = context.memory_context_query(
        label="Créer et rendre rentable l’entreprise — cycle 42",
        objective=objective,
    )

    assert query == "Créer et rendre rentable l’entreprise d’ici septembre 2027"
    assert "cycle" not in query.casefold()
    assert len(query) <= 240


def test_memory_context_query_falls_back_to_a_short_objective() -> None:
    query = context.memory_context_query(
        label="Task",
        objective=" ".join(f"word{index}" for index in range(100)),
    )

    assert query.split() == [f"word{index}" for index in range(18)]
    assert len(query) <= 240


def test_memory_context_query_ignores_decorated_conversation_label() -> None:
    query = context.memory_context_query(
        label="Conversation — aster-test",
        objective="Générer une scène 3D détaillée de la Tour Eiffel.",
        contact_terms=("Nicolas", "nicolas", "nextcloud_talk"),
    )

    assert query == (
        "Nicolas nicolas nextcloud_talk "
        "Générer une scène 3D détaillée de la Tour Eiffel."
    )
    assert "aster-test" not in query


def test_conversation_memory_queries_drop_speaker_markup_and_use_recent_history() -> None:
    objective = "[Nicolas] Tu peux réessayer stp ?"
    history = (
        {"role": "user", "text": "Prépare la scène 3D de la maison normande."},
        {"role": "assistant", "text": "La vérification visuelle a échoué."},
    )

    lexical = context.memory_context_query(
        label="Conversation — nova-code",
        objective=objective,
    )
    semantic = context.memory_context_semantic_query(
        label="Conversation — nova-code",
        objective=objective,
        conversation_history=history,
    )

    assert lexical == "Tu peux réessayer stp ?"
    assert semantic.startswith("Tu peux réessayer stp ?")
    assert "maison normande" in semantic
    assert "vérification visuelle" in semantic
    assert "Nicolas" not in semantic
    assert "nova-code" not in semantic


def test_memory_context_query_removes_a_task_cycle_suffix() -> None:
    query = context.memory_context_query(
        label="Déployer la nouvelle mémoire — cycle 42",
        objective="A self-contained objective without a structured Goal title.",
    )

    assert query == "Déployer la nouvelle mémoire"


def test_memory_context_query_binds_the_exact_human_contact() -> None:
    query = context.memory_context_query(
        label="Préparer son compte rendu",
        objective="Résumer les décisions du projet.",
        contact_terms=("Alice Martin", "@alice:example.org", "matrix"),
    )

    assert query.startswith("Alice Martin @alice:example.org matrix")
    assert "Préparer son compte rendu" in query


def test_memory_policy_requires_a_relevance_check_not_an_automatic_search() -> None:
    policy = context.memory_policy_instructions()
    normalized = " ".join(policy.split())

    assert "requires this relevance check, not an automatic search" in normalized
    assert "one short query" in normalized
    assert "memory_remember" in normalized
    assert "do not wait for an explicit request to remember it" in normalized
    assert "working document" not in normalized
    assert "provisional drafts or notes" in normalized
    assert "written first" in normalized
    assert "identifies one item unambiguously" in normalized
    assert "Never guess which memory to erase" in normalized
    assert "authoritative galaris:// business resource" in normalized


@pytest.mark.asyncio
async def test_memory_context_provider_injects_policy_and_bounded_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_queries: list[str] = []
    captured_scopes: list[tuple[UUID | None, UUID | None]] = []
    topic_id = uuid4()
    topic_item_id = uuid4()
    contact_item_id = uuid4()

    async def fake_build_memory_brief(
        *,
        agent_id: int,
        query: str,
        semantic_query: str | None,
        task_id: UUID | None,
        topic_item_id: UUID | None,
        contact_item_id: UUID | None,
        strict_contact_scope: bool,
        include_relevant: bool,
        include_experience: bool,
        stage: str,
    ) -> MemoryBrief:
        assert agent_id == 7
        assert task_id is not None
        assert include_experience is False
        # Human rounds keep global unscoped memory while excluding memories
        # explicitly owned by another contact in the retrieval service.
        assert strict_contact_scope is False
        assert include_relevant is True
        assert stage == "execution"
        assert semantic_query is not None
        assert "Déployer la nouvelle mémoire — cycle 42" in semantic_query
        assert "Use prior deployment knowledge" in semantic_query
        captured_queries.append(query)
        captured_scopes.append((topic_item_id, contact_item_id))
        return MemoryBrief(query=query, items=(), rendered="")

    async def fake_projected_topic_item_id(value: UUID | None) -> UUID | None:
        assert value == topic_id
        return topic_item_id

    monkeypatch.setattr(
        bootstrap.runtime_settings,
        "MEMORY_CONTEXT_ENABLED",
        True,
    )
    monkeypatch.setattr(
        bootstrap,
        "build_memory_brief",
        fake_build_memory_brief,
    )
    monkeypatch.setattr(
        bootstrap,
        "projected_topic_item_id",
        fake_projected_topic_item_id,
    )

    contribution = await bootstrap.memory_context_provider(
        replace(
            _request(
                label="Déployer la nouvelle mémoire — cycle 42",
                task_data={
                    "sender.user_id": "@alice:example.org",
                    "sender.display_name": "Alice Martin",
                    "sender_is_ai": False,
                },
                topic_id=topic_id,
                contact_memory_item_id=contact_item_id,
            ),
            messenger_connection_id=73,
        )
    )

    assert captured_queries == ["Déployer la nouvelle mémoire"]
    assert captured_scopes == [(None, contact_item_id)]
    assert "<durable-memory-policy>" in contribution.system_instructions
    assert contribution.shared_context == ""
    assert contribution.metadata == {
        "memory_context_enabled": True,
        "memory_context_query": "Déployer la nouvelle mémoire",
        "memory_context_count": 0,
        "memory_context_truncated": False,
    }


@pytest.mark.asyncio
async def test_memory_context_provider_injects_filtered_brief_without_contact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory_id = uuid4()

    async def fake_build_memory_brief(**_kwargs: object) -> MemoryBrief:
        return MemoryBrief(
            query="deployment",
            items=(
                MemoryContextItem(
                    memory_id=str(memory_id),
                    title="Deployment convention",
                    excerpt="Apply Atlas first.",
                    score=0.8,
                    memory_type="procedural",
                ),
            ),
            rendered="## Long-term memory\n\nApply Atlas first.",
        )

    async def fake_projected_topic_item_id(_value: UUID | None) -> None:
        return None

    monkeypatch.setattr(bootstrap.runtime_settings, "MEMORY_CONTEXT_ENABLED", True)
    monkeypatch.setattr(bootstrap, "build_memory_brief", fake_build_memory_brief)
    monkeypatch.setattr(
        bootstrap,
        "projected_topic_item_id",
        fake_projected_topic_item_id,
    )

    contribution = await bootstrap.memory_context_provider(
        _request(label="Deployment", contact_memory_item_id=None)
    )

    assert contribution.shared_context.endswith("Apply Atlas first.")
    assert [candidate.reference for candidate in contribution.candidates] == [
        str(memory_id)
    ]
    assert contribution.metadata["memory_context_count"] == 1
