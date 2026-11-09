"""Exercise input collection invariants through real services, replacing only the model."""

# Shared pytest fixture imports intentionally populate the module fixture namespace.
# ruff: noqa: F811

import asyncio
from dataclasses import replace
from uuid import UUID

import pytest
from sqlalchemy import func, select

from app.conversation.mcp import conversation_process_prepare, conversation_process_start
from app.conversation.models import ConversationRound
from app.conversation.tests.test_process_inputs import assessment, context, human, human_turn, inference, workflow
from app.file_share import ResourceContext, resource_create, resource_delete
from app.process.models import ProcessRun, ProcessStartJob, ProcessRunEvent
from app.process.tests.test_native_bpmn import native as native, committed_native as committed_native
from app.process.values import Variable
from app.tools import RecoverableToolError
from core.database import get_db, get_db_session


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,invalid,correct", [
    ("int", "42", 42), ("int", False, 0), ("int", 2.5, 2),
    ("bool", "false", False), ("bool", 0, False),
    ("string", 42, "Synthetic"),
    ("date", "2001-02-29", "2000-02-29"), ("date", "31/12/2000", "2000-12-31"),
    ("datetime", "2000-01-01T12:00:00", "2000-01-01T12:00:00Z"),
    ("array", {}, [0, False, ""]), ("object", [], {"value": False, "type": "business"}),
])
async def test_validation_and_retries_are_deterministic_and_keep_the_final_parameter_scope_check(db, native, monkeypatch, kind, invalid, correct):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="known", type="string", nullable=False), Variable(name="answer", type=kind, nullable=True)])
    calls = inference(monkeypatch, [assessment(single=True)], [[{"workflow_id": definition.code,
        "input": {"known": "Synthetic", "answer": correct}}]])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier using my known details.", user)
    first = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"known": "Synthetic"})
    original_revision = (await db.get(ConversationRound, turn.round_id)).process_preparations[definition.code]["revision"]
    repeated = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    assert repeated["missing"] == ["answer"] and len(calls) == 1
    assert (await db.get(ConversationRound, turn.round_id)).process_preparations[definition.code]["revision"] == original_revision
    failed = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"answer": invalid})
    assert failed["status"] == "collecting" and "answer" in failed["issues"]
    retry = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    assert retry["issues"] == failed["issues"] and retry["input"]["known"]["value"] == "Synthetic"
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"answer": correct})
    assert ready["status"] == "ready" and not ready["issues"] and len(calls) == 1
    launched = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert launched["run_id"] == first["run_id"] and launched["started"] and len(calls) == 2
    assert (await db.get(ProcessRun, UUID(launched["run_id"]))).input["answer"] == ready["input"]["answer"]
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["new-round", "text", "attachments"])
async def test_a_changed_human_contribution_cannot_reuse_earlier_intent(db, native, monkeypatch, change):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="answer", type="string", nullable=True)])
    calls = inference(monkeypatch, [assessment(single=True), assessment(action="cancel", consent=False)])
    turn, room = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    first = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    if change == "new-round":
        changed, _ = await human_turn(db, owner, "Cancel my dossier.", user, room=room)
    elif change == "text":
        changed = replace(turn, source_request="Cancel my dossier.")
    else:
        changed = replace(turn, messages=({"text": "Cancel my dossier.", "files": []},))
    result = await conversation_process_start(context(changed), workflow_id=definition.code, input={"answer": "Synthetic"})
    assert result["status"] == "cancelled" and len(calls) == 2
    assert (await db.get(ProcessRun, UUID(first["run_id"]))).status == "cancelled"
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_withdrawing_launch_consent_keeps_complete_data_waiting_until_confirmed(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True), assessment({"name": "Synthetic"}, consent=False),
        assessment(single=True)])
    first, room = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    waiting = await conversation_process_prepare(context(first), workflow_id=definition.code)
    second, _ = await human_turn(db, owner, "My name is Synthetic. Keep the dossier ready, but do not launch yet.", user, room=room)
    paused = await conversation_process_start(context(second), workflow_id=definition.code)
    assert not paused["missing"] and paused["status"] == "collecting" and not paused["launch_requested"]
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
    third, _ = await human_turn(db, owner, "Yes, launch it now.", user, room=room)
    started = await conversation_process_start(context(third), workflow_id=definition.code)
    assert started["run_id"] == waiting["run_id"] and started["started"] and len(calls) == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
async def test_single_assessed_launch_avoids_duplicate_permission_but_ambiguity_retains_it(db, native, monkeypatch, single):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="answer", type="int", nullable=False)])
    plan = [[{"workflow_id": definition.code, "input": {"answer": 0}}]] if not single else []
    calls = inference(monkeypatch, [assessment({"answer": 0}, single=single)], plan)
    turn, _ = await human_turn(db, owner, "Launch the synthetic dossier with answer zero.", user)
    await conversation_process_prepare(context(turn), workflow_id=definition.code)
    run = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert run["started"] and len(calls) == (1 if single else 2)
    saved = (await db.get(ConversationRound, turn.round_id)).process_launch_admission
    assert ("preparation" in saved) is single
    assert not (await conversation_process_start(context(turn), workflow_id=definition.code))["started"]
    assert len(calls) == (1 if single else 2)


@pytest.mark.asyncio
async def test_a_frozen_refusal_cannot_be_overridden_by_prepared_launch_intent(db, native, monkeypatch):
    from app.conversation.process_admission import admit_process_launch
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False)])
    calls = inference(monkeypatch, [assessment({"name": "Synthetic"}, single=True)], [[]])
    turn, _ = await human_turn(db, owner, "Prepare one synthetic dossier.", user)
    with pytest.raises(RecoverableToolError):
        await admit_process_launch(turn, definition.code, {"name": "Synthetic"})
    await conversation_process_prepare(context(turn), workflow_id=definition.code)
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=definition.code)
    assert len(calls) == 2 and await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_old_attachment_evidence_survives_later_messages_and_still_requires_live_access(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    file = await resource_create(ctx, "file://", b"Synthetic original file", name="Synthetic.txt")
    definition = await workflow(owner, [Variable(name="document", type="File", nullable=True), Variable(name="name", type="string", nullable=True)])
    calls = inference(monkeypatch, [assessment(single=True), assessment({"document": file.uri, "name": "Synthetic"}, single=True)])
    first, room = await human_turn(db, owner, "Launch one dossier; here is the document.", user, files=[file.uri])
    waiting = await conversation_process_prepare(context(first), workflow_id=definition.code)
    second, _ = await human_turn(db, owner, "My name is Synthetic.", user, room=room)
    ready = await conversation_process_prepare(context(second), workflow_id=definition.code)
    assert ready["status"] == "ready" and ready["input"]["document"]["value"] == file.uri
    await resource_delete(ctx, file.uri)
    revoked = await conversation_process_start(context(second), workflow_id=definition.code)
    assert revoked["status"] == "collecting" and "document" in revoked["missing"]
    assert revoked["run_id"] == waiting["run_id"] and len(calls) == 2
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_document_uri_cannot_be_invented_from_a_prefix_or_an_assistant_question(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    file = await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "file://", b"Synthetic", name="Synthetic.txt")
    definition = await workflow(owner, [Variable(name="document", type="File", nullable=True)])
    calls = inference(monkeypatch, [assessment({"document": file.uri}, question=f"Unsupported assistant hint {file.uri}", single=True),
        assessment({"document": file.uri}, single=True)])
    first, room = await human_turn(db, owner, "Launch one synthetic dossier.", user, files=[file.uri + "-different-resource"])
    rejected = await conversation_process_prepare(context(first), workflow_id=definition.code)
    assert "document" in rejected["issues"] and not rejected["input"]
    second, _ = await human_turn(db, owner, "Continue the collection.", user, room=room)
    again = await conversation_process_prepare(context(second), workflow_id=definition.code)
    assert "document" in again["issues"] and not again["input"] and len(calls) == 2
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("occurrence", [False, True, 0, -1, 21])
async def test_invalid_occurrences_do_not_spend_a_model_call_or_create_a_waiting_run(db, native, monkeypatch, occurrence):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    calls = inference(monkeypatch, [])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=definition.code, occurrence=occurrence)
    assert not calls and await db.scalar(select(func.count()).select_from(ProcessRun)) == 0


@pytest.mark.asyncio
async def test_two_workers_collecting_the_same_input_recover_one_receipt(inference_db, committed_native, monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel
    from app.llm import llm_service, structured_service
    db = inference_db
    owner, _ = committed_native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    entered = 0
    together = asyncio.Event()
    async def respond(_messages, info):
        nonlocal entered
        entered += 1
        if entered == 2:
            together.set()
        await asyncio.wait_for(together.wait(), 3)
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, assessment(single=True))])
    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=SimpleNamespace(id=987)))
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=FunctionModel(respond)))
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0.0)
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    async def prepare():
        async with get_db_session():
            return await conversation_process_prepare(context(turn), workflow_id=definition.code)
    first, second = await asyncio.gather(prepare(), prepare())
    assert first["run_id"] == second["run_id"]
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.event_type == "run.created")) == 1
    assert entered == 2


@pytest.mark.asyncio
async def test_nested_typed_null_survives_default_start_and_replay_without_retyping(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="items", type="array", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier with these known values.", user)
    nested = {"items": {"type": "array", "value": [{"type": "string", "value": None},
        {"type": "bool", "value": False}, {"type": "int", "value": 0}]}}
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code, input=nested, typed_values=True)
    started = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert started["run_id"] == ready["run_id"] and started["started"] and len(calls) == 1
    stored = await db.get(ProcessRun, UUID(started["run_id"]))
    assert stored.input == nested and stored.data == nested
    assert not (await conversation_process_start(context(turn), workflow_id=definition.code))["started"]
    assert stored.input == nested and len(calls) == 1


@pytest.mark.asyncio
async def test_a_valid_supplied_file_replaces_a_now_unavailable_default(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    old = await resource_create(ctx, "file://", b"Synthetic old", name="Old.txt")
    fresh = await resource_create(ctx, "file://", b"Synthetic replacement", name="Fresh.txt")
    definition = await workflow(owner, [Variable(name="document", type="File", nullable=False,
        default={"type": "File", "value": old.uri})])
    await resource_delete(ctx, old.uri)
    calls = inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one dossier with this replacement.", user, files=[fresh.uri])
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"document": fresh.uri})
    assert ready["status"] == "ready" and not ready["issues"]
    started = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert started["started"] and (await db.get(ProcessRun, UUID(started["run_id"]))).input["document"]["value"] == fresh.uri
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("language,prefix", [("en", "Please provide"), ("fr", "Merci de fournir")])
async def test_followup_questions_name_only_unresolved_fields_without_another_model_call(db, native, monkeypatch, language, prefix):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="field_left", type="string", nullable=False),
        Variable(name="field_done", type="string", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    turn = replace(turn, language=language)
    await conversation_process_prepare(context(turn), workflow_id=definition.code)
    updated = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"field_done": "Synthetic"})
    assert updated["question"].startswith(prefix)
    assert "field_left" in updated["question"] and "field_done" not in updated["question"] and len(calls) == 1


@pytest.mark.asyncio
async def test_repeating_an_unsupported_null_placeholder_reuses_the_refusal_without_another_model_call(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    calls = inference(monkeypatch, [assessment({"name": None}, single=True)])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    first = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"name": None})
    again = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"name": None})
    assert first["missing"] == again["missing"] == ["name"]
    assert len(calls) == 1 and not again["input"]


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["value", "typed-mode", "workflow", "participant"])
async def test_prepared_permission_never_authorizes_changed_parameters_or_scope(db, native, monkeypatch, change):
    from app.conversation.process_admission import admit_process_launch
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="answer", type="int", nullable=False)])
    other = await workflow(owner, [Variable(name="answer", type="int", nullable=False)])
    calls = inference(monkeypatch, [assessment({"answer": 0}, single=True)], [[]])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier with zero.", user)
    await conversation_process_prepare(context(turn), workflow_id=definition.code)
    args = {"workflow_id": other.code if change == "workflow" else definition.code,
        "values": {"answer": 1 if change == "value" else 0}, "typed_values": change == "typed-mode"}
    changed = replace(turn, messaging_context={**turn.messaging_context, "participant_id": "synthetic-other"}) if change == "participant" else turn
    with pytest.raises(RecoverableToolError):
        await admit_process_launch(changed, **args)
    assert len(calls) == 2 and await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_explicit_multiple_runs_keep_the_full_launch_plan_and_distinct_invocations(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False)])
    launch = {"workflow_id": definition.code, "input": {"name": "Synthetic"}}
    calls = inference(monkeypatch, [assessment({"name": "Synthetic"}, single=False)], [[launch, launch]])
    turn, _ = await human_turn(db, owner, "Launch this synthetic dossier twice for Synthetic.", user)
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    first = await conversation_process_start(context(turn), workflow_id=definition.code)
    second = await conversation_process_start(context(turn), workflow_id=definition.code, occurrence=2)
    assert first["run_id"] == ready["run_id"] and second["run_id"] != first["run_id"]
    assert len(calls) == 2 and await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 2
    saved = (await db.get(ConversationRound, turn.round_id)).process_launch_admission
    assert "preparation" not in saved and len(saved["plan"]["launches"]) == 2


@pytest.mark.asyncio
async def test_direct_complete_native_input_is_entirely_deterministic(db, native, monkeypatch):
    from app.process import process_service
    owner, _ = native
    definition = await workflow(owner, [Variable(name="count", type="int", nullable=False)])
    calls = inference(monkeypatch, [])
    result = await process_service.start_process(agent_id=owner.id, workflow_id=definition.code,
        input_data={"count": {"type": "int", "value": 0}})
    assert result.status == "queued" and not calls


@pytest.mark.asyncio
async def test_a_superseded_worker_interrupts_its_lock_wait_without_changing_the_dossier(inference_db, committed_native, monkeypatch):
    from sqlalchemy import event
    from app.conversation import ConversationSuperseded
    from unittest.mock import AsyncMock
    db = inference_db
    owner, _ = committed_native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False)])
    inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier.", user)
    first = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    superseded = False
    waiting_for_lock = asyncio.Event()
    connection = await db.connection()
    engine = connection.sync_connection.engine
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        if "FOR UPDATE OF conversation_rounds" in statement:
            waiting_for_lock.set()
    async def update():
        async with get_db_session():
            return await conversation_process_prepare(context(replace(turn,
                should_interrupt=AsyncMock(side_effect=lambda: superseded))), workflow_id=definition.code, input={"name": "Synthetic"})
    async with get_db_session():
        await get_db().scalar(select(ConversationRound).where(ConversationRound.id == turn.round_id).with_for_update())
        event.listen(engine, "before_cursor_execute", capture)
        worker = asyncio.create_task(update())
        try:
            await asyncio.wait_for(waiting_for_lock.wait(), 3)
            superseded = True
            with pytest.raises(ConversationSuperseded):
                await asyncio.wait_for(worker, 2)
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
            event.remove(engine, "before_cursor_execute", capture)
    await db.refresh(await db.get(ProcessRun, UUID(first["run_id"])))
    assert (await db.get(ProcessRun, UUID(first["run_id"]))).input == {}
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


def test_resource_evidence_keeps_exact_references_without_scanning_long_non_uri_text_quadratically():
    from app.conversation.process_inputs import _resource_evidence
    import time
    started = time.perf_counter()
    evidence = _resource_evidence("x-y." * 50_000, {"uri": "console://synthetic/name."},
        "Read (file://synthetic-reference).", ["file://synthetic-reference-extra"])
    assert evidence == {"console://synthetic/name.", "file://synthetic-reference", "file://synthetic-reference-extra"}
    assert time.perf_counter() - started < 2


@pytest.mark.asyncio
async def test_values_added_after_an_assessment_cannot_expand_its_approved_parameter_scope(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="amount", type="int", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True)], [[{"workflow_id": definition.code, "input": {"amount": 10}}]])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier with amount 10.", user)
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"amount": 10})
    await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"amount": 1000})
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=definition.code)
    assert len(calls) == 2 and await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
    await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"amount": 10})
    result = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert result["run_id"] == ready["run_id"] and result["started"] and len(calls) == 2
    assert (await db.get(ProcessRun, UUID(result["run_id"]))).input["amount"]["value"] == 10


@pytest.mark.asyncio
async def test_a_conflict_between_proposed_and_human_values_keeps_the_exact_scope_check(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False)])
    calls = inference(monkeypatch, [assessment({"name": "Synthetic Alice"}, single=True)],
        [[{"workflow_id": definition.code, "input": {"name": "Synthetic Alice"}}]])
    turn, _ = await human_turn(db, owner, "Launch one dossier for Synthetic Alice.", user)
    await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"name": "Synthetic Bob"})
    with pytest.raises(RecoverableToolError):
        await conversation_process_start(context(turn), workflow_id=definition.code)
    assert len(calls) == 2 and await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.parametrize("ambiguous", [None, 0, 1, "true", "yes", []])
def test_single_launch_permission_requires_an_explicit_json_boolean(ambiguous):
    from pydantic import ValidationError
    from app.conversation.process_inputs import ProcessInputAssessment
    with pytest.raises(ValidationError):
        ProcessInputAssessment.model_validate({"action": "collect", "launch_requested": True, "single_launch": ambiguous})


@pytest.mark.asyncio
async def test_concurrent_partial_updates_report_a_conflict_then_retry_without_losing_data(inference_db, committed_native, monkeypatch):
    from sqlalchemy import event
    db = inference_db
    owner, _ = committed_native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="first", type="string", nullable=False), Variable(name="last", type="string", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one dossier using my known details.", user)
    waiting = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    engine = (await db.connection()).sync_connection.engine
    both_waiting = asyncio.Event()
    lock_requests = 0
    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        nonlocal lock_requests
        if "FOR UPDATE OF conversation_rounds" in statement:
            lock_requests += 1
            if lock_requests == 2:
                both_waiting.set()
    patches = [{"first": "Synthetic"}, {"last": "Example"}]
    async def submit(patch):
        async with get_db_session():
            return await conversation_process_prepare(context(turn), workflow_id=definition.code, input=patch)
    tasks = []
    async with get_db_session():
        await get_db().scalar(select(ConversationRound).where(ConversationRound.id == turn.round_id).with_for_update())
        event.listen(engine, "before_cursor_execute", capture)
        try:
            tasks = [asyncio.create_task(submit(patch)) for patch in patches]
            await asyncio.wait_for(both_waiting.wait(), 3)
        finally:
            event.remove(engine, "before_cursor_execute", capture)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert sum(isinstance(result, RecoverableToolError) for result in results) == 1
    assert sum(isinstance(result, dict) for result in results) == 1
    index = next(index for index, result in enumerate(results) if isinstance(result, RecoverableToolError))
    ready = await submit(patches[index])
    assert ready["run_id"] == waiting["run_id"] and ready["status"] == "ready" and len(calls) == 1
    assert ready["input"]["first"]["value"] == "Synthetic" and ready["input"]["last"]["value"] == "Example"
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_a_released_run_replays_its_receipt_even_when_its_original_file_was_deleted(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    file = await resource_create(ctx, "file://", b"Synthetic original", name="Synthetic.txt")
    definition = await workflow(owner, [Variable(name="document", type="File", nullable=False)])
    calls = inference(monkeypatch, [assessment(single=True)])
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier with this file.", user, files=[file.uri])
    await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"document": file.uri})
    started = await conversation_process_start(context(turn), workflow_id=definition.code)
    await resource_delete(ctx, file.uri)
    receipt = await conversation_process_start(context(turn), workflow_id=definition.code, input={"document": file.uri})
    assert receipt["run_id"] == started["run_id"] and not receipt["started"] and len(calls) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1
