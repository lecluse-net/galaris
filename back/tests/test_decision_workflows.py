"""Real profile resolution and durable inference; only provider HTTP is replaced."""

import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.llm import llm_service, model_usages
from app.llm.models import LLMCall
from app.llm.profile_models import LlmProfile
from app.topic import TopicCandidate, classifier
from app.topic.sequential_detection import (
    PromptedTopicDetectionModel,
    TemporalContinuityPrior,
)
from app.dream.contracts import (
    MemoryExtractionInput,
    MemoryExtractionMessage,
    MemoryExtractionExistingMemory,
)
from app.dream.mechanisms.memory_extraction import (
    run_memory_extraction,
    MEMORY_EXTRACTION_SYSTEM_PROMPT,
)
from tests.test_decision_inference import decisions, runtime  # noqa: F401
from tests.test_dispatcher_inference import dispatch_context
from app.dream.tests.test_memory_extraction import memory_extraction_storage  # noqa: F401


async def profile_context(decisions, runtime, *, specialized=True, fallback=True):
    from app.task import task_service

    db, request, _, _, _ = decisions
    _, text_model, _, _ = runtime
    _, _, task_id, _ = await dispatch_context(db, "task")
    task = await task_service.get_by_id(task_id)
    profile = LlmProfile(
        label=f"closed-choices-{uuid4()}",
        text_ultra_low_llm_id=text_model.id,
        decision_llm_id=request.llm_id if specialized else None,
        decision_fallback_policy="text_on_failure" if fallback else "disabled",
    )
    db.add(profile)
    await db.flush()
    task.agent.profile_id = profile.id
    await db.commit()
    return task, profile


@pytest.mark.asyncio
@pytest.mark.parametrize("new_topic", [False, True])
async def test_topic_reuse_avoids_writer_and_novel_subject_uses_writer(
    decisions, runtime, new_topic
):
    db, _, native_calls, text_calls, mode = decisions
    _, _, _, text_mode = runtime
    task, _ = await profile_context(decisions, runtime)
    candidate = TopicCandidate(id=uuid4(), title="Gardening", description="Growing plants.")
    mode["selections"] = {"topic": "new" if new_topic else str(candidate.id)}
    text_mode["outputs"] = [json.dumps({"title": "Astronomy", "description": "Studying the sky."})]
    result, cost = await classifier.classify(
        activity="Observe Saturn." if new_topic else "Grow tomatoes.",
        candidates=[candidate],
        task_id=task.id,
        agent_id=task.agent_id,
        language="en",
    )
    assert result.action == ("create" if new_topic else "reuse")
    assert result.title == "Astronomy" if new_topic else result.topic_id == candidate.id
    assert len(native_calls) == 1
    assert len(text_calls) == int(new_topic)
    assert cost >= 0.0002
    if not new_topic:
        assert result.confidence is None  # no fabricated certainty
    persisted = list(await db.scalars(select(LLMCall)))
    assert any(call.purpose == "dream.topic_reuse" for call in persisted)


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["same", "different"])
async def test_topic_continuity_uses_a_choice_without_inventing_a_probability(
    decisions, runtime, choice
):
    _, _, native_calls, text_calls, mode = decisions
    _, text_model, _, _ = runtime
    task, _ = await profile_context(decisions, runtime)
    mode["selections"] = {"continuity": choice}
    model = PromptedTopicDetectionModel(
        text_model, task_id=task.id, agent_id=task.agent_id, use_decision_profile=True
    )
    output, cost = await model.interpret_continuity(
        rendered_window='{"current_message":true,"text":"And the soil?"}',
        current_topic=TopicCandidate(id=uuid4(), title="Gardening"),
        temporal_prior=TemporalContinuityPrior(
            probability=0.75, timestamp_quality="missing", version="test"
        ),
    )
    assert output.selected_same_topic is (choice == "same")
    assert output.same_topic_probability is None
    assert output.decision_inference["source"] == "specialized"
    assert len(native_calls) == 1 and not text_calls
    assert cost == pytest.approx(0.0002)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retention,link,writer",
    [
        ("ignore", "skip", False),
        ("link", "link", False),
        ("extract", "link", True),
        ("link", "skip", True),
        ("ignore", "link", True),
    ],
)
async def test_memory_gate_links_without_rewriting_and_preserves_mixed_facts(
    decisions, runtime, retention, link, writer
):
    _, _, native_calls, text_calls, mode = decisions
    _, text_model, _, text_mode = runtime
    task, _ = await profile_context(decisions, runtime)
    memory_id = str(uuid4())
    mode["selections"] = {"retention": retention, "memory_0": link}
    new_fact = {
        "action": "CREATE",
        "title": "Preferred output format",
        "content": "Morgan prefers concise tables.",
        "memory_type": "semantic",
        "retention_reason": "explicit_user_preference",
        "future_utility": "high",
    }
    text_mode.update(structured=False, outputs=[json.dumps({"operations": [new_fact]})])
    input_data = MemoryExtractionInput(
        source_kind="task",
        topic={"title": "Preferences"},
        current=[
            MemoryExtractionMessage(
                speaker_name="Morgan",
                speaker_kind="human",
                text="Keep answering in English, and use concise tables from now on.",
            )
        ],
        existing_memories=[
            MemoryExtractionExistingMemory(
                id=memory_id, title="Language", content="Morgan prefers English."
            )
        ],
    )
    prepared, cost = await run_memory_extraction(
        llm=text_model,
        input_data=input_data,
        system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
        task_id=task.id,
        agent_id=task.agent_id,
        language_instruction="Write in English.",
    )
    assert len(native_calls) == 1 and len(text_calls) == int(writer)
    assert prepared.decision_inference["source"] == "specialized"
    assert cost >= 0.0002
    operations = prepared.decision.operations
    if writer:
        assert operations[0].content == new_fact["content"]
        assert input_data.current[0].text in json.dumps(text_calls, ensure_ascii=False)
    elif retention == "link":
        assert operations[0].target_memory_id == memory_id
    else:
        assert operations == []


@pytest.mark.asyncio
async def test_custom_profile_without_decision_does_not_borrow_global_model(
    decisions, runtime, monkeypatch
):
    from unittest.mock import AsyncMock
    from app.llm import profile_service

    db, request, native_calls, text_calls, _ = decisions
    _, text_model, _, text_mode = runtime
    task, profile = await profile_context(decisions, runtime, specialized=False)
    global_profile = LlmProfile(
        label=f"Global specialist {uuid4()}",
        decision_llm_id=request.llm_id,
        text_ultra_low_llm_id=text_model.id,
    )
    db.add(global_profile)
    await db.commit()
    monkeypatch.setattr(
        profile_service, "get_current_profile_id", AsyncMock(return_value=global_profile.id)
    )
    text_mode.update(structured=False, outputs=['{"operations":[]}'])
    prepared, _ = await run_memory_extraction(
        llm=text_model,
        input_data=MemoryExtractionInput(
            source_kind="task",
            topic={"title": "Greetings"},
            current=[
                MemoryExtractionMessage(speaker_name="Morgan", speaker_kind="human", text="Hello!")
            ],
        ),
        system_prompt=MEMORY_EXTRACTION_SYSTEM_PROMPT,
        task_id=task.id,
        agent_id=task.agent_id,
        language_instruction="Write in English.",
    )
    assert profile.decision_llm_id is None
    assert prepared.decision.operations == [] and prepared.decision_inference is None
    assert not native_calls and len(text_calls) == 1
    assert await llm_service.get_decision_models_for_agent_id(987654321, model_usages.DREAM) == (
        None,
        None,
        False,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("fallback", [True, False])
async def test_dream_profile_honours_decision_fallback_policy(decisions, runtime, fallback):
    _, _, native_calls, text_calls, mode = decisions
    _, _, _, text_mode = runtime
    task, _ = await profile_context(decisions, runtime, fallback=fallback)
    candidate = TopicCandidate(id=uuid4(), title="Gardening")
    mode.update(status=503, selections={"topic": str(candidate.id)})
    text_mode["outputs"] = [json.dumps({"selections": {"topic": str(candidate.id)}})]
    operation = classifier.classify(
        activity="Grow tomatoes.",
        candidates=[candidate],
        task_id=task.id,
        agent_id=task.agent_id,
        language="en",
    )
    if fallback:
        result, _ = await operation
        assert result.topic_id == candidate.id
    else:
        with pytest.raises(RuntimeError):
            await operation
    assert len(native_calls) == 1 and len(text_calls) == int(fallback)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "choice,stale,fail_after_apply",
    [
        ("merge", False, False),
        ("separate", False, False),
        ("merge", True, False),
        ("merge", False, True),
    ],
)
async def test_memory_similarity_needs_semantic_agreement_and_fresh_candidate(
    decisions,
    runtime,
    monkeypatch,
    memory_extraction_storage,
    choice,
    stale,
    fail_after_apply,
):
    from sqlalchemy import update
    from app.memory import deduplication, service
    from app.memory.acquisition_service import acquire_memory
    from app.memory.embedding import EmbeddingModel
    from app.memory.models import MemoryItem
    from app.memory.schemas import MemoryItemCreate, MemoryPayload, MemoryAcquisitionCreate
    from app.memory.tests.embedding_fixtures import published_chunk

    db, _, calls, text_calls, mode = decisions
    task, _ = await profile_context(decisions, runtime)
    original = "Morgan sends reports every month."
    existing, _ = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=task.agent_id,
            title="Reporting cadence",
            payload=MemoryPayload(text=original),
        )
    )
    model = EmbeddingModel(
        key="synthetic-embedding",
        code="synthetic-vector",
        model_name="synthetic-vector",
        base_url="http://vector.test/v1",
        api_key=None,
    )
    db.add(
        published_chunk(
            item_id=existing.id,
            source_fingerprint=existing.semantic_fingerprint,
            model_key=model.key,
            model_code=model.code,
            dimensions=3,
            chunk_index=0,
            text=existing.search_text,
            embedding=[1.0, 0.0, 0.0],
        )
    )
    await db.commit()

    async def vector_model():
        return model

    async def embeddings(texts, **kwargs):
        return [[1.0, 0.0, 0.0] for _ in texts]

    monkeypatch.setattr(deduplication, "resolve_embedding_model", vector_model)
    monkeypatch.setattr(deduplication, "embed_many", embeddings)
    mode["selections"] = {"duplicate": choice}
    if stale:

        async def revise_during_inference():
            await db.execute(
                update(MemoryItem)
                .where(MemoryItem.id == existing.id)
                .values(revision=MemoryItem.revision + 1)
            )
            await db.commit()

        mode["before_response"] = revise_during_inference
    data = MemoryAcquisitionCreate(
        agent_id=task.agent_id,
        action="create",
        title="Cadence preference",
        content="A report is sent by Morgan each month.",
        source_kind="task",
        source_ref=f"galaris://task/{task.id}",
        idempotency_key=f"synthetic-acquisition-{uuid4()}",
    )
    from datetime import datetime, timedelta, timezone
    from unittest.mock import AsyncMock
    from app.dream import scheduler
    from app.dream.contracts import DreamClaim
    from app.dream.models import DreamReceipt
    from app.dream.service import receipt_correlation_ref

    receipt = DreamReceipt(
        mechanism_key="memory.extract_task",
        subject_kind="task",
        subject_id=str(task.id),
        lease_token=uuid4(),
        lease_expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        status="running",
        attempts=1,
        prepared_payload={},
        cost=0.001,
    )
    db.add(receipt)
    await db.commit()
    results = []

    class PreparedAcquisition:
        key = "memory.extract_task"

        async def apply(self, claim, payload):
            results.append(await acquire_memory(data))
            if fail_after_apply:
                raise RuntimeError("Synthetic failure after acquisition")
            return 1

    monkeypatch.setattr(scheduler, "has_active_voice_calls", lambda: False)
    monkeypatch.setattr("app.memory.automation.enqueue_dream_link_reconciliation", AsyncMock())
    await scheduler._run_claim(
        PreparedAcquisition(),
        DreamClaim(
            receipt_id=receipt.id,
            lease_token=receipt.lease_token,
            subject_kind="task",
            subject_id=str(task.id),
            attempts=1,
            prepared_payload={},
        ),
    )
    result = results[0]
    await db.refresh(receipt)
    assert receipt.status == ("retry" if fail_after_apply else "success")
    assert receipt.cost == pytest.approx(0.0012)
    call = await db.scalar(select(LLMCall).where(LLMCall.purpose == "memory.duplicate_decision"))
    assert call.correlation_ref == receipt_correlation_ref(receipt.id)
    merged = choice == "merge" and not stale
    assert (result.memory_id == existing.id) is merged
    assert result.status == ("merged" if merged else "stored")
    assert len(calls) == 1 and not text_calls
    replay = await acquire_memory(data)
    assert replay.memory_id == result.memory_id and len(calls) == 1
    _, content, _, _, _ = await service.get_item(existing.id, agent_id=task.agent_id)
    assert original in content.decode()


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["topic_classification", "memory_extraction"])
@pytest.mark.parametrize("scenario", ["native", "text", "failure", "changed_writer"])
async def test_lab_freezes_hybrid_models_and_never_substitutes_candidate(
    decisions,
    runtime,
    monkeypatch,
    mechanism,
    scenario,
):
    from unittest.mock import AsyncMock
    from app.llm import profile_service
    from app.lab import mechanism_evaluation_service as service
    from app.lab.run_claims import claim_next_run
    from app.lab.run_inference import evaluate_claim
    from app.lab.schemas import (
        MechanismDatasetCreate,
        EvaluationCaseCreate,
        MechanismCaseUpdate,
        EvaluationRunStart,
    )

    db, request, native_calls, text_calls, mode = decisions
    _, text_model, _, text_mode = runtime
    _, profile = await profile_context(decisions, runtime)
    monkeypatch.setattr(
        profile_service, "get_current_profile_id", AsyncMock(return_value=profile.id)
    )
    topic = mechanism == "topic_classification"
    dataset = await service.create_dataset(
        mechanism, MechanismDatasetCreate(name=f"Synthetic hybrid {uuid4()}")
    )
    case = await service.create_case(mechanism, dataset.id, EvaluationCaseCreate(name="Greeting"))
    await service.update_case(
        mechanism,
        case.id,
        MechanismCaseUpdate(
            revision=case.revision,
            input_data={
                "variable_value": ["Hello again!"],
                "context": {
                    "initial_topic": {"title": "Greetings"},
                }
                if topic
                else {"topic": {"title": "Greetings"}},
            },
            expected_output={"topics": ["Greetings"]}
            if topic
            else {
                "operations": [],
                "relevant_memory_ids": [],
                "ranked_memory_ids": [],
            },
        ),
    )
    queued = await service.start_run(
        mechanism,
        dataset.id,
        EvaluationRunStart(
            llm_id=text_model.id if scenario == "text" else request.llm_id,
            judge_llm_id=text_model.id,
        ),
    )
    if scenario != "text":
        assert queued.configuration_snapshot["generation_llm_snapshot"]["id"] == text_model.id
        # Later profile edits must not redirect the admitted writer or decision model.
        profile.decision_llm_id = None
        profile.text_ultra_low_llm_id = None
    if scenario == "changed_writer":
        text_model.llm_name = "changed-after-admission"
    await db.commit()
    mode["selections"] = {"continuity": "same"} if topic else {"retention": "extract"}
    if scenario == "failure":
        mode["status"] = 503
    text_mode.update(
        structured=False,
        outputs=[
            '{"same_topic_probability":0.99,"reason":"Greeting continued."}'
            if topic
            else '{"operations":[]}'
        ],
    )
    claim = await claim_next_run()
    assert claim.work is not None and claim.work.run_id == queued.id
    result = await evaluate_claim(claim.work)
    if scenario in {"failure", "changed_writer"}:
        assert result.error
        assert not text_calls
        assert len(native_calls) == int(scenario == "failure")
    else:
        assert result.error is None, result.error
        assert len(native_calls) == int(scenario == "native")
        assert len(text_calls) == int(scenario == "text" or not topic)
        assert (
            result.actual_output["topics"] == ["Greetings"]
            if topic
            else result.actual_output["operations"] == []
        )
        calls = list(await db.scalars(select(LLMCall)))
        assert result.cost == pytest.approx(sum(call.cost for call in calls))
