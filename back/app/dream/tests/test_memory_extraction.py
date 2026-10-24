from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.dream.contracts import (
    MAX_MEMORY_EXTRACTION_CANDIDATES,
    MemoryCreateOperation,
    MemoryEnrichOperation,
    MemoryContradictOperation,
    MemoryExtractionDecision,
    MemoryExtractionExistingMemory,
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryExtractionPrepared,
    MemoryLinkOperation,
)
from app.dream.mechanisms.memory_extraction import (
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
    MemoryExtractionApplicationError,
    apply_memory_extraction,
    existing_memories_from_hits,
    memory_extraction_prepared_from_payload,
    parse_memory_extraction_decision,
    rank_existing_memories,
    run_memory_extraction,
    validate_memory_extraction_decision,
)
from app.dream.mechanisms import memory_extraction
from app.llm.provider_models import LLM
from app.llm.structured_service import StructuredInferenceResult
from app.memory.contracts import SourceMemoryDocument
from app.memory import service as memory_service
from app.document.schemas import DocumentItemCreate, DocumentPayload
from app.memory.tests.document_fixtures import create_document_reference
from app.memory.schemas import (
    MemoryAcquisitionResult,
    MemoryItemCreate,
    MemoryPayload,
    MemorySearchHit,
    MemoryItemUpdate,
)
from core.storage import NativeFileStorage, register_storage, reset_storage_registry


@pytest.fixture
def memory_extraction_storage(tmp_path: Path) -> Path:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        yield tmp_path
    finally:
        reset_storage_registry()


async def _owner(db: AsyncSession) -> Agent:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Memory extraction test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Memory",
        code=f"memory-extraction-{suffix}",
        agent_driver="internal",
    )
    db.add(owner)
    await db.flush()
    return owner


def test_default_prompt_actively_detects_single_durable_facts() -> None:
    prompt = " ".join(MEMORY_EXTRACTION_SYSTEM_PROMPT.split())

    assert "A fact can be durable even when it is stated only once" in prompt
    assert "Do not require words such as \"remember\"" in prompt
    assert "A concrete Task outcome may support" in prompt
    assert "Do not discard a qualifying fact" in prompt
    assert "Do not compare the potential memory with a node as two whole documents" in prompt
    assert "speaker_name as authoritative attribution metadata" in prompt
    assert "Abstain by default" not in prompt


def test_canonical_prompt_default_matches_the_builtin_contract() -> None:
    backend_root = Path(__file__).resolve().parents[3]
    defaults = backend_root / "core" / "params" / "prompt_defaults"

    path = defaults / "ai.memory-extraction-system-prompt.md"
    packaged = " ".join(path.read_text(encoding="utf-8").split())
    builtin = " ".join(MEMORY_EXTRACTION_SYSTEM_PROMPT.split())
    assert packaged == builtin


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["ENRICH", "CONTRADICT"])
async def test_continuity_preserves_content_sources_and_replay(db, memory_extraction_storage, action):
    owner = await _owner(db)
    existing, _ = await memory_service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Workshop policy",
        payload=MemoryPayload(text="<p>The workshop welcomes beginners.</p>"), media_type="text/html",
        keywords=["workshop"],
    ))
    operation_type = MemoryEnrichOperation if action == "ENRICH" else MemoryContradictOperation
    values = dict(target_memory_id=str(existing.id), title=existing.title,
                  content="<p>Participants may borrow cameras.</p>" if action == "ENRICH" else "<p>Only experienced participants may join.</p>",
                  keywords=["cameras"], retention_reason="recurring_constraint", future_utility="high")
    if action == "ENRICH":
        values["expected_revision"] = existing.revision
    operation = operation_type.model_validate(values)
    prepared = MemoryExtractionPrepared(decision=MemoryExtractionDecision(operations=[operation]), candidate_memory_ids=[existing.id])
    arguments = dict(agent_id=owner.id, source_kind="task", source_ref=f"task:{uuid4()}",
                     source_excerpt="Synthetic workshop policy", memory_created_at=datetime.now(timezone.utc),
                     metadata={"media_type": "text/html"}, contact_item_id=None, topic_item_id=None,
                     idempotency_prefix=f"continuity:{uuid4()}")
    first = await apply_memory_extraction(prepared, **arguments)
    second = await apply_memory_extraction(prepared, **arguments)
    assert first == second
    original, content, *_ = await memory_service.get_item(existing.id, agent_id=owner.id)
    assert b"welcomes beginners" in content
    if action == "ENRICH":
        assert first.operations[0].memory_id == existing.id
        assert b"borrow cameras" in content
        assert original.keywords == ["workshop", "cameras"]
        assert original.revision == 2
        assert arguments["source_ref"] in await memory_service.source_refs(existing.id)
    else:
        assert first.operations[0].memory_id != existing.id
        assert b"experienced" not in content
        links = await memory_service.list_links(existing.id, actor_agent_id=owner.id)
        assert [(link.relation_type, link.target_item_id) for link in links] == [("contradicts", first.operations[0].memory_id)]


def test_enrichment_requires_an_allowed_editable_candidate_with_the_seen_revision():
    candidate = MemoryExtractionExistingMemory(id=str(uuid4()), title="Policy", content="Existing fact", revision=3, can_enrich=True)
    operation = MemoryEnrichOperation(target_memory_id=candidate.id, expected_revision=3, title="Policy", content="Complementary fact",
                                     retention_reason="recurring_constraint", future_utility="high")
    for can_enrich, revision in [(False, 3), (True, 4), (True, 3)]:
        current = candidate.model_copy(update={"can_enrich": can_enrich, "revision": revision})
        result = validate_memory_extraction_decision(MemoryExtractionDecision(operations=[operation]),
            allowed_memory_ids={candidate.id}, candidates={candidate.id: current})
        assert bool(result.operations) == (can_enrich and revision == 3)


@pytest.mark.asyncio
async def test_enrichment_rejects_a_concurrent_edit_without_losing_either_content(db, memory_extraction_storage):
    owner = await _owner(db)
    existing, _ = await memory_service.create_item(MemoryItemCreate(owner_agent_id=owner.id,
        title="Workshop policy", payload=MemoryPayload(text="<p>Initial policy.</p>"), media_type="text/html"))
    prepared = MemoryExtractionPrepared(decision=MemoryExtractionDecision(operations=[MemoryEnrichOperation(
        target_memory_id=str(existing.id), expected_revision=existing.revision, title="Workshop policy",
        content="<p>A complementary fact.</p>", retention_reason="recurring_constraint", future_utility="high",
    )]), candidate_memory_ids=[existing.id])
    await memory_service.update_item(existing.id, MemoryItemUpdate(expected_revision=existing.revision,
        payload=MemoryPayload(text="<p>A concurrent correction.</p>")), actor_agent_id=owner.id)
    with pytest.raises(memory_service.MemoryConflictError, match="changed before enrichment"):
        await apply_memory_extraction(prepared, agent_id=owner.id, source_kind="task", source_ref="task:stale-enrichment",
            source_excerpt="A complementary fact.", memory_created_at=datetime.now(timezone.utc), metadata={"media_type": "text/html"},
            contact_item_id=None, topic_item_id=None, idempotency_prefix=f"stale:{uuid4()}")
    _, content, *_ = await memory_service.get_item(existing.id, agent_id=owner.id)
    assert b"concurrent correction" in content and b"complementary" not in content
    assert "task:stale-enrichment" not in await memory_service.source_refs(existing.id)


def test_case_local_memory_corpus_is_limited_to_ten() -> None:
    memories = [
        MemoryExtractionExistingMemory(
            id=f"memory-{index:03d}",
            title=f"Souvenir {index}",
            content=f"Contenu durable {index}",
        )
        for index in range(MAX_MEMORY_EXTRACTION_CANDIDATES + 1)
    ]

    with pytest.raises(ValidationError):
        MemoryExtractionInput(
            source_kind="task",
            topic={"title": "Test"},
            current=[
                MemoryExtractionMessage(
                    speaker_name="Nicolas",
                    speaker_kind="human",
                    text="Test",
                )
            ],
            existing_memories=memories,
        )


def test_local_ranking_is_deterministic_and_limited() -> None:
    input_data = MemoryExtractionInput(
        source_kind="conversation_round",
        topic={"title": "Préférences"},
        current=[
            MemoryExtractionMessage(
                speaker_name="Nicolas",
                speaker_kind="human",
                text="Je préfère le café noir",
            )
        ],
        existing_memories=[
            MemoryExtractionExistingMemory(
                id="unrelated",
                title="Voyage",
                content="La personne voyage en train.",
            ),
            MemoryExtractionExistingMemory(
                id="coffee",
                title="Café noir",
                content="La personne préfère le café noir.",
            ),
        ],
    )

    ranked = rank_existing_memories(input_data, limit=1)

    assert [item.id for item in ranked] == ["coffee"]


@pytest.mark.parametrize("target,refs", [("invented", []), ("memory-001", ["invented-evidence"])])
def test_invalid_link_targets_are_dropped_server_side(target, refs) -> None:
    decision = MemoryExtractionDecision(
        operations=[MemoryLinkOperation(target_memory_id=target, evidence_refs=refs)]
    )

    validated = validate_memory_extraction_decision(
        decision,
        allowed_memory_ids={"memory-001"},
        allowed_evidence_refs={"source-evidence"},
    )

    assert validated.operations == []


def test_normalized_operations_are_not_duplicated() -> None:
    decision = MemoryExtractionDecision.model_validate(
        {
            "operations": [
                {
                    "action": "link",
                    "target_memory_id": "memory-001",
                    "reason": "The source confirms the durable fact.",
                }
            ]
        }
    )

    assert decision.operations == [
        MemoryLinkOperation(
            target_memory_id="memory-001",
            reason="The source confirms the durable fact.",
        )
    ]
    enrichment = MemoryEnrichOperation(target_memory_id="memory-001", expected_revision=1,
        title="Workshop policy", content="Complementary fact.", retention_reason="recurring_constraint", future_utility="high")
    with pytest.raises(ValidationError, match="one ENRICH per target revision"):
        MemoryExtractionDecision(operations=[enrichment, enrichment])


def test_malformed_json_is_rejected_instead_of_repaired() -> None:
    with pytest.raises(ValueError, match="valid JSON object"):
        parse_memory_extraction_decision(
            '{"{"operations":[{"action":"LINK",'
            '"target_memory_id":"aac941e5-3da0-47fe-a713-5b8a9487cc74",'
            '"reason":"Cette source confirme le souvenir."}]}'
        )


@pytest.mark.asyncio
async def test_every_recalled_node_is_shown_for_fact_containment(
    db: AsyncSession,
    memory_extraction_storage: Path,
) -> None:
    del memory_extraction_storage
    owner = await _owner(db)
    profile = await memory_service.upsert_source_managed_item(
        SourceMemoryDocument(
            source_kind="agent",
            source_ref=f"agent:{owner.id}",
            owner_agent_id=owner.id,
            memory_item_id=None,
            title="Fiche de poste complète",
            content=(
                "L'agent pilote la fiabilité de la plateforme. "
                "Il privilégie des changements simples et vérifiables."
            ),
            filename="agent.md",
            keywords=("fiabilité", "simplicité"),
            metadata={"memory_role": "agent"},
        )
    )
    document, _created = await create_document_reference(
        DocumentItemCreate(
            owner_agent_id=owner.id,
            title="Guide de livraison",
            payload=DocumentPayload(text="Les livraisons ont lieu chaque mardi."),
        )
    )
    profile_item, _profile_content, profile_access, *_ = await memory_service.get_item(
        profile.id,
        agent_id=owner.id,
    )
    document_item, _document_content, document_access, *_ = await memory_service.get_item(
        document.id,
        agent_id=owner.id,
    )
    profile_public = memory_service.item_to_public(profile_item, profile_access)
    document_public = memory_service.item_to_public(document_item, document_access)

    candidates = existing_memories_from_hits(
        [
            MemorySearchHit(
                item=profile_public,
                excerpt="Il privilégie des changements simples et vérifiables.",
                score=0.71,
                semantic_similarity=0.71,
            ),
            MemorySearchHit(
                item=document_public,
                excerpt="Les livraisons ont lieu chaque mardi.",
                score=0.68,
                semantic_similarity=0.68,
            ),
        ],
        owner_agent_id=owner.id,
        source_text="Le changement doit rester simple.",
    )

    assert [candidate.id for candidate in candidates] == [
        str(profile.id),
        str(document.id),
    ]
    assert candidates[0].content == (
        "Il privilégie des changements simples et vérifiables."
    )


@pytest.mark.asyncio
async def test_memory_extraction_retries_invalid_json_before_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            '{"{"operations":[]}',
            '{"operations":[]}',
        ]
    )
    prompts: list[dict[str, Any]] = []

    async def fake_run_text(**kwargs: Any) -> StructuredInferenceResult[str]:
        prompts.append(kwargs)
        return StructuredInferenceResult(
            output=next(responses),
            cost=0.01,
            messages=[],
        )

    monkeypatch.setattr(memory_extraction, "run_text", fake_run_text)
    prepared, cost = await run_memory_extraction(
        llm=cast(LLM, object()),
        use_decision_profile=False,
        input_data=MemoryExtractionInput(
            source_kind="task",
            topic={"title": "Préférences"},
            current=[
                MemoryExtractionMessage(
                    speaker_name="Nicolas",
                    speaker_kind="human",
                    text="Réponds toujours en français.",
                )
            ],
        ),
        system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
        task_id=None,
        agent_id=1,
        language_instruction="Required output language: French.",
    )

    assert prepared.decision.operations == []
    assert cost == pytest.approx(0.02)
    assert len(prompts) == 2
    assert all(prompt["request_limit"] is None for prompt in prompts)
    assert "previous response was rejected" in prompts[1]["system_prompt"]


@pytest.mark.asyncio
async def test_memory_extraction_fails_when_every_json_attempt_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    async def fake_run_text(**_kwargs: Any) -> StructuredInferenceResult[str]:
        nonlocal calls
        calls += 1
        return StructuredInferenceResult(
            output="not-json",
            cost=0.01,
            messages=[],
        )

    monkeypatch.setattr(memory_extraction, "run_text", fake_run_text)
    with pytest.raises(ValueError, match="exhausted its valid-JSON attempts"):
        await run_memory_extraction(
            llm=cast(LLM, object()),
            use_decision_profile=False,
            input_data=MemoryExtractionInput(
                source_kind="task",
                topic={"title": "Préférences"},
                current=[
                    MemoryExtractionMessage(
                        speaker_name="Nicolas",
                        speaker_kind="human",
                        text="Réponds toujours en français.",
                    )
                ],
            ),
            system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
            task_id=None,
            agent_id=1,
            language_instruction="Required output language: French.",
        )

    assert calls == 2


def test_low_confidence_create_is_parsed_then_dropped_server_side() -> None:
    decision = MemoryExtractionDecision.model_validate(
        {
            "operations": [
                {
                    "action": "create",
                    "title": "Possible preference",
                    "content": "The source may suggest concise answers.",
                },
                {"action": "ignore", "reason": "Nothing else is durable."},
            ]
        }
    )

    assert validate_memory_extraction_decision(
        decision,
        allowed_memory_ids=set(),
    ).operations == []


@pytest.mark.parametrize("legacy_summary", [False, True])
def test_current_checkpoint_is_validated(legacy_summary: bool) -> None:
    operation = {
        "action": "CREATE",
        "title": "Language preference",
        "content": "<p>Always answer in French.</p>",
        "retention_reason": "explicit_user_preference",
        "future_utility": "high",
    }
    if legacy_summary:
        operation["summary"] = "Obsolete independent description"
    prepared = memory_extraction_prepared_from_payload(
        {
            "decision": {"operations": [operation]},
            "candidate_memory_ids": [],
        }
    )

    retained = prepared.decision.operations[0]
    assert isinstance(retained, MemoryCreateOperation)
    assert retained.content == operation["content"]
    assert "summary" not in retained.model_dump()
    assert "summary" not in MemoryCreateOperation.model_json_schema()["properties"]
    assert "summary" not in MemoryExtractionExistingMemory.model_json_schema()["properties"]
    assert prepared.candidate_memory_ids == []


@pytest.mark.asyncio
@pytest.mark.parametrize("node_kind", ["memory", "document"])
async def test_link_adds_provenance_without_rewriting_existing_memory(
    db: AsyncSession,
    memory_extraction_storage: Path,
    node_kind: str,
) -> None:
    del memory_extraction_storage
    owner = await _owner(db)
    values = dict(owner_agent_id=owner.id, title="Préférence de réponse", payload={"text": "La personne préfère les réponses concises."})
    if node_kind == "document":
        existing, _created = await create_document_reference(DocumentItemCreate.model_validate(values))
    else:
        existing, _created = await memory_service.create_item(MemoryItemCreate.model_validate(values))
    _, original_content, _, _, _ = await memory_service.get_item(
        existing.id, agent_id=owner.id,
    )
    original_revision = existing.revision
    prepared = MemoryExtractionPrepared(
        decision=MemoryExtractionDecision(
            operations=[
                MemoryLinkOperation(
                    target_memory_id=str(existing.id),
                    reason="La source confirme exactement cette préférence.",
                )
            ]
        ),
        candidate_memory_ids=[existing.id],
    )

    application = await apply_memory_extraction(
        prepared,
        agent_id=owner.id,
        source_kind="task",
        source_ref="task:memory-link-test",
        source_excerpt="Réponds-moi toujours de façon concise.",
        memory_created_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        metadata={"evidence_validator": "conversation", "source_evidence": []},
        contact_item_id=None,
        topic_item_id=None,
        idempotency_prefix="dream:memory-link-test",
    )

    item, content, _access, _content_type, _media_type = await memory_service.get_item(
        existing.id,
        agent_id=owner.id,
    )
    assert len(application.operations) == 1
    assert application.operations[0].action == "LINK"
    assert item.revision == original_revision
    assert content == original_content
    if node_kind == "memory":
        assert application.operations[0].memory_id == existing.id
        assert application.operations[0].status == "merged"
        assert await memory_service.source_refs(existing.id) == ["task:memory-link-test"]
    else:
        # Personal evidence belongs to a private memory, never the shared Document.
        assert application.operations[0].memory_id != existing.id
        assert application.operations[0].status == "stored"
        assert await memory_service.source_refs(existing.id) == []
        assert await memory_service.source_refs(application.operations[0].memory_id) == ["task:memory-link-test"]


@pytest.mark.asyncio
async def test_rejected_memory_operation_fails_instead_of_claiming_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def reject_acquisition(*_args: Any, **_kwargs: Any) -> MemoryAcquisitionResult:
        return MemoryAcquisitionResult(
            acquisition_id=uuid4(),
            memory_id=None,
            created=True,
            applied=True,
            status="rejected",
        )

    monkeypatch.setattr(memory_extraction, "acquire_memory", reject_acquisition)
    prepared = MemoryExtractionPrepared(
        decision=MemoryExtractionDecision(
            operations=[
                MemoryCreateOperation(
                    title="Validated pricing decision",
                    content="The pricing increase is validated.",
                    retention_reason="explicit_decision_or_commitment",
                    future_utility="high",
                )
            ]
        )
    )

    with pytest.raises(
        MemoryExtractionApplicationError,
        match=r"Operation 0 was not persisted \(status=rejected\)",
    ):
        await apply_memory_extraction(
            prepared,
            agent_id=1,
            source_kind="conversation_round",
            source_ref="conversation_round:rejected-test",
            source_excerpt="The pricing increase is validated.",
            memory_created_at=datetime(2026, 8, 17, tzinfo=timezone.utc),
            metadata={},
            contact_item_id=None,
            topic_item_id=None,
            idempotency_prefix="dream:rejected-test",
        )


@pytest.mark.asyncio
async def test_server_reports_a_threshold_merge_as_a_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_id = uuid4()

    async def merge_acquisition(
        *_args: Any,
        **_kwargs: Any,
    ) -> MemoryAcquisitionResult:
        return MemoryAcquisitionResult(
            acquisition_id=uuid4(),
            memory_id=existing_id,
            created=True,
            applied=True,
            status="merged",
        )

    monkeypatch.setattr(memory_extraction, "acquire_memory", merge_acquisition)
    prepared = MemoryExtractionPrepared(
        decision=MemoryExtractionDecision(
            operations=[
                MemoryCreateOperation(
                    title="Monthly report",
                    content="The reporting cadence is monthly.",
                    retention_reason="recurring_constraint",
                    future_utility="high",
                )
            ]
        )
    )

    application = await apply_memory_extraction(
        prepared,
        agent_id=1,
        source_kind="task",
        source_ref="task:threshold-merge",
        source_excerpt="The reporting cadence is monthly.",
        memory_created_at=datetime(2026, 8, 24, tzinfo=timezone.utc),
        metadata={},
        contact_item_id=None,
        topic_item_id=None,
        idempotency_prefix="dream:threshold-merge",
    )

    assert application.operations[0].action == "LINK"
    assert application.operations[0].status == "merged"
    MemoryExtractionPrepared(
        decision=prepared.decision,
        application=application,
    )
