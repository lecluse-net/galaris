"""Collect real typed inputs across human turns before admitting exactly one run."""

# Imported pytest fixtures are intentionally injected into test parameters.
# ruff: noqa: F811

from dataclasses import replace
import asyncio
from datetime import timedelta
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
from pypdf import PdfWriter
import pytest
from sqlalchemy import func, select, update

from app.conversation.mcp import conversation_process_prepare, conversation_process_start
from app.conversation.models import ConversationProcessLink, ConversationRound
from app.conversation.process_inputs import pending_process_preparations
from app.conversation.tests.test_process_admission import conversation, context
from app.file_share import ResourceContext, resource_create
from app.llm import llm_service, structured_service
from app.process import process_service
from app.process.bpmn import Flow, Node, Workflow
from app.process.models import ProcessRun, ProcessStartJob, ProcessNodeRun
from app.process.native_definitions import create
from app.process.tests.test_native_bpmn import native as native, committed_native as committed_native, finish_run
from app.process.values import Variable, ValueContractError
from app.tools import RecoverableToolError
from core.user import UserModel
from core.database import get_db_session


def inference(monkeypatch, assessments, launches=()):
    from pydantic_ai.messages import ModelResponse, ToolCallPart
    from pydantic_ai.models.function import FunctionModel

    assessments, launches = iter(assessments), iter(launches)
    requests = []
    def respond(messages, info):
        schema = info.output_tools[0].parameters_json_schema
        collecting = "action" in schema.get("properties", {})
        requests.append({"collecting": collecting, "messages": str(messages)})
        payload = next(assessments) if collecting else {"launches": next(launches)}
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])
    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=SimpleNamespace(id=987)))
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=FunctionModel(respond)))
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0.0)
    return requests


async def human_turn(db, owner, text, user, *, room=None, files=()):
    if room is not None:
        await db.execute(update(ConversationRound).where(ConversationRound.room_id == room.id,
            ConversationRound.status == "RUNNING").values(status="SUCCEEDED"))
    turn, room = await conversation(db, owner, text, room=room)
    row = await db.get(ConversationRound, turn.round_id)
    row.requester_user_id = user.id
    from app.messenger import Message
    from app.conversation.models import ConversationRoundMessage
    message = await db.scalar(select(Message).join(ConversationRoundMessage,
        ConversationRoundMessage.message_id == Message.id).where(ConversationRoundMessage.round_id == row.id))
    message.requester_user_id = user.id
    await db.commit()
    return replace(turn, messages=({"text": text, "files": [{"uri": uri} for uri in files]},),
        messaging_context={"requester_user_id": user.id, "participant_id": f"synthetic:{user.id}"}), room


async def human(db, label="one"):
    user = UserModel(email=f"synthetic-input-{label}@example.invalid", hashed_password="synthetic", is_active=True)
    db.add(user)
    await db.flush()
    return user


async def workflow(owner, variables):
    names = [item.name for item in variables]
    return await create(actor_agent_id=owner.id, title="Synthetic complete dossier", graph=Workflow(
        schema_version="galaris.bpmn/v2", variables=variables,
        nodes=[Node(id="start", kind="start", inputs=names), Node(id="end", kind="end", outputs=names)],
        flows=[Flow(id="done", source="start", target="end")]))


def assessment(values=None, *, action="collect", question="Provide the missing information.", consent=True, evidence=None, single=False):
    return {"action": action, "launch_requested": consent, "values": values or {}, "question": question,
        "searches": ["Search authorized Memory and existing documents before asking again."], "null_evidence": evidence or {}, "single_launch": single}


@pytest.mark.asyncio
async def test_nullable_selected_inputs_cannot_be_omitted_even_through_direct_process_launch(db, native):
    owner, _ = native
    definition = await workflow(owner, [Variable(name="portrait", type="File", nullable=True),
        Variable(name="birth_date", type="date", nullable=True)])
    with pytest.raises(ValueContractError, match="missing selected process inputs.*portrait.*birth_date"):
        await process_service.start_process(agent_id=owner.id, workflow_id=definition.code, input_data={})
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0


@pytest.mark.asyncio
async def test_dossier_reuses_known_values_collects_documents_and_launches_once_after_later_reply(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    resource = ResourceContext(agent_id=owner.id, runtime="internal")
    picture = BytesIO()
    Image.new("RGB", (8, 8), "blue").save(picture, format="PNG")
    portrait = await resource_create(resource, "file://", picture.getvalue(), name="Synthetic.png")
    pdf = BytesIO()
    writer = PdfWriter(); writer.add_blank_page(width=80, height=40); writer.write(pdf)
    permit = await resource_create(resource, "file://", pdf.getvalue(), name="Synthetic.pdf")
    variables = [Variable(name="portrait", type="File", nullable=True, mime_type="image/*"),
        Variable(name="permit", type="File", nullable=True, mime_type="application/pdf"),
        Variable(name="age", type="int", nullable=True), Variable(name="first_name", type="string", nullable=True),
        Variable(name="last_name", type="string", nullable=True), Variable(name="birth_date", type="date", nullable=True),
        Variable(name="confirmed", type="bool", nullable=False, default={"type": "bool", "value": False})]
    definition = await workflow(owner, variables)
    expected = {"portrait": portrait.uri, "permit": permit.uri, "age": 0, "first_name": "Synthetic",
        "last_name": "Example", "birth_date": "2000-02-29", "confirmed": False}
    requests = inference(monkeypatch, [assessment({"age": 0, "first_name": "Synthetic"}, question="Please provide permit, last name and birth date."),
        assessment({"permit": permit.uri, "last_name": "Example", "birth_date": "2000-02-29"}, question="")],
        [[{"workflow_id": definition.code, "input": expected}]])
    first, room = await human_turn(db, owner, "Launch my synthetic dossier. My first name is Synthetic and age is 0.", user, files=[portrait.uri])
    result = await conversation_process_start(context(first), workflow_id=definition.code, input={"portrait": portrait.uri})
    assert result["status"] == "collecting" and result["created"] is True and result["started"] is False
    assert set(result["missing"]) == {"permit", "last_name", "birth_date"}
    assert result["input"]["confirmed"]["value"] is False and result["input"]["age"]["value"] == 0
    waiting = await db.scalar(select(ProcessRun))
    assert str(waiting.id) == result["run_id"] and waiting.status == "waiting" and waiting.started_at is None
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
    await process_service.refresh_run(waiting.id)
    await process_service.process_start_jobs(engine_code="galaris")
    assert await db.scalar(select(func.count()).select_from(ProcessNodeRun)) == 0
    from app.process.facade import active_work_for_agent
    active = await active_work_for_agent(owner.id)
    assert active[0]["status"] == "waiting" and active[0]["waits"][0]["kind"] == "process_inputs"
    assert set(active[0]["waits"][0]["missing"]) == set(result["missing"])
    from app.process.native_runs import control_run
    with pytest.raises(ValueError, match="awaits its selected inputs"):
        await control_run(waiting.id, owner.id, "resume")
    # Editing the definition cannot change inputs already frozen on the waiting run.
    from app.process.native_definitions import read, update
    saved = await read(definition.code, owner.id)
    edited = Workflow.model_validate(saved["graph"])
    edited.variables.append(Variable(name="new_requirement", type="string", nullable=False))
    edited.node("start").inputs.append("new_requirement")
    await update(definition.code, owner.id, expected_revision=saved["revision"], graph=edited)
    assert (await db.get(ConversationRound, first.round_id)).process_launch_admission is None
    second, _ = await human_turn(db, owner, "My last name is Example, born 2000-02-29. Here is the permit.", user, room=room, files=[permit.uri])
    pending = await pending_process_preparations(second)
    assert len(pending) == 1 and pending[0]["kind"] == "process_input_preparation"
    ready = await conversation_process_prepare(context(second), workflow_id=definition.code)
    assert ready["status"] == "ready" and not ready["missing"]
    launched = await conversation_process_start(context(second), workflow_id=definition.code)
    assert launched["started"] is True and launched["run_id"] == result["run_id"]
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1
    replay = await conversation_process_start(context(replace(second, attempt=2)), workflow_id=definition.code)
    assert replay["created"] is False and replay["run_id"] == launched["run_id"]
    assert not (await conversation_process_start(context(second), workflow_id=definition.code, input=expected))["created"]
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert len(requests) == 3 and "original_request" in requests[-1]["messages"]
    await process_service.process_start_jobs(engine_code="galaris")
    from uuid import UUID
    run = await finish_run(db, UUID(launched["run_id"]))
    assert run.status == "success" and run.output["permit"]["value"] == permit.uri
    assert await pending_process_preparations(second) == ()


@pytest.mark.asyncio
async def test_participants_cancellation_and_unrelated_messages_never_fill_or_launch_another_dossier(db, native, monkeypatch):
    owner, _ = native
    first_user, other_user = await human(db), await human(db, "two")
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True), Variable(name="age", type="int", nullable=True)])
    inference(monkeypatch, [assessment(), assessment(consent=False), assessment(action="unrelated", consent=False), assessment(action="cancel", consent=False)])
    first, room = await human_turn(db, owner, "Launch the synthetic dossier for Synthetic.", first_user)
    await conversation_process_start(context(first), workflow_id=definition.code, input={"name": "Synthetic"})
    # Newer dossiers owned by other participants must not hide this pending one.
    origin = await db.get(ConversationRound, first.round_id)
    db.add_all([ConversationRound(room_id=room.id, status="SUCCEEDED",
        created_at=origin.created_at + timedelta(seconds=index + 1),
        process_preparations={"noise": {"scope": "another-participant", "status": "collecting"}}) for index in range(21)])
    await db.commit()
    assert len(await pending_process_preparations(first)) == 1
    other, _ = await human_turn(db, owner, "Help with my own dossier.", other_user, room=room)
    assert await pending_process_preparations(other) == ()
    independent = await conversation_process_prepare(context(other), workflow_id=definition.code)
    assert "name" in independent["missing"]
    unrelated, _ = await human_turn(db, owner, "What is the weather?", first_user, room=room)
    assert (await conversation_process_start(context(unrelated), workflow_id=definition.code))["status"] == "unrelated"
    cancelled, _ = await human_turn(db, owner, "Cancel my pending dossier.", first_user, room=room)
    assert (await conversation_process_prepare(context(cancelled), workflow_id=definition.code))["status"] == "cancelled"
    assert await pending_process_preparations(cancelled) == ()
    assert (await db.scalar(select(ProcessRun))).status == "cancelled"
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_null_placeholders_are_missing_until_the_human_explicitly_acknowledges_absence(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="permit", type="File", nullable=True)])
    inference(monkeypatch, [assessment({"permit": None}), assessment({"permit": None}, evidence={"permit": "I do not have a permit."})])
    first, room = await human_turn(db, owner, "Launch the dossier.", user)
    result = await conversation_process_start(context(first), workflow_id=definition.code, input={"permit": None})
    assert result["status"] == "collecting" and result["missing"] == ["permit"]
    assert (await db.scalar(select(ProcessRun))).status == "waiting"
    second, _ = await human_turn(db, owner, "I do not have a permit.", user, room=room)
    result = await conversation_process_prepare(context(second), workflow_id=definition.code)
    assert result["status"] == "ready" and result["input"]["permit"]["value"] is None
    repeated = await conversation_process_prepare(context(second), workflow_id=definition.code, input={"permit": None})
    assert repeated["status"] == "ready" and repeated["input"] == result["input"]


@pytest.mark.asyncio
async def test_single_pronoun_relaunch_reuses_actual_context_and_corrects_occurrence_without_rephrasing(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="city", type="string", nullable=True)])
    launch = [{"workflow_id": definition.code, "input": {"city": "Oslo"}}]
    requests = inference(monkeypatch, [assessment({"city": "Oslo"}, question="")], [launch, launch])
    first, room = await human_turn(db, owner, "Launch the synthetic workflow for Oslo.", user)
    original = await conversation_process_start(context(first), workflow_id=definition.code, input={"city": "Oslo"})
    second, _ = await human_turn(db, owner, "Relaunch it for me please.", user, room=room)
    with pytest.raises(RecoverableToolError, match="single new relaunch uses occurrence=1"):
        await conversation_process_start(context(second), workflow_id=definition.code, occurrence=2)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 2
    assert len(list(await db.scalars(select(ProcessRun).where(ProcessRun.status == "waiting")))) == 1
    result = await conversation_process_start(context(second), workflow_id=definition.code)
    assert result["started"] and result["run_id"] != original["run_id"]
    assert any("recent_actual_runs" in request["messages"] and "Oslo" in request["messages"] for request in requests)
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", ["mime", "date", "forbidden", "missing"])
async def test_invalid_dates_and_wrong_document_formats_remain_unresolved_without_launch(db, native, monkeypatch, invalid):
    owner, reader = native
    user = await human(db)
    image = BytesIO()
    Image.new("RGB", (4, 4), "white").save(image, format="PNG")
    picture = await resource_create(ResourceContext(agent_id=reader.id if invalid == "forbidden" else owner.id,
        runtime="internal"), "file://", image.getvalue(), name="Synthetic.png")
    definition = await workflow(owner, [Variable(name="permit", type="File", nullable=True,
        mime_type="application/pdf" if invalid == "mime" else None),
        Variable(name="birth_date", type="date", nullable=True)])
    proposed = ({"birth_date": "2000-02-30"} if invalid == "date" else
        {"permit": "file://00000000-0000-0000-0000-000000000001" if invalid == "missing" else picture.uri})
    inference(monkeypatch, [assessment(proposed)])
    turn, _ = await human_turn(db, owner, "Launch this synthetic dossier with the supplied information.", user, files=[picture.uri])
    result = await conversation_process_start(context(turn), workflow_id=definition.code, input=proposed)
    assert result["status"] == "collecting" and result["created"] is True and result["started"] is False
    assert set(proposed) <= set(result["issues"]) and set(proposed) <= set(result["missing"])
    assert not result["input"]
    assert (await db.scalar(select(ProcessRun))).status == "waiting"
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_late_assessment_and_provider_failure_never_save_values_or_launch(inference_db, committed_native, monkeypatch):
    from app.conversation import ConversationSuperseded
    from app.conversation import process_inputs

    db = inference_db
    owner, _ = committed_native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    requests = inference(monkeypatch, [assessment({"name": "Synthetic"})])
    turn, _ = await human_turn(db, owner, "Launch a dossier for Synthetic.", user)
    stale = replace(turn, should_interrupt=AsyncMock(side_effect=lambda: bool(requests)))
    with pytest.raises(ConversationSuperseded):
        await conversation_process_start(context(stale), workflow_id=definition.code)
    assert len(requests) == 1
    assert (await db.get(ConversationRound, turn.round_id)).process_preparations is None
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(side_effect=RuntimeError("Synthetic outage")))
    with pytest.raises(RecoverableToolError, match="could not be assessed"):
        await conversation_process_prepare(context(turn), workflow_id=definition.code)
    cancelled = asyncio.Event()
    async def silent_provider(*args, **kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(structured_service, "build_model_for_llm", silent_provider)
    monkeypatch.setattr(process_inputs, "_PREPARATION_TIMEOUT_SECONDS", 0.5)
    with pytest.raises(RecoverableToolError, match="timed out"):
        await asyncio.wait_for(conversation_process_prepare(context(turn), workflow_id=definition.code), 2)
    assert cancelled.is_set()
    assert (await db.get(ConversationRound, turn.round_id)).process_preparations is None
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 0


@pytest.mark.asyncio
async def test_concurrent_recovery_of_ready_dossier_creates_one_run_and_one_link(inference_db, committed_native, monkeypatch):
    from app.conversation.process_admission import admit_process_launch

    db = inference_db
    owner, _ = committed_native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    workflow_id = definition.code
    requests = inference(monkeypatch, [assessment({"name": "Synthetic"}, question="")],
        [[{"workflow_id": workflow_id, "input": {"name": "Synthetic"}}]])
    turn, _ = await human_turn(db, owner, "Launch the dossier for Synthetic.", user)
    ready = await conversation_process_prepare(context(turn), workflow_id=workflow_id)
    assert ready["status"] == "ready"
    await admit_process_launch(turn, workflow_id, {"name": "Synthetic"})
    async def launch():
        async with get_db_session():
            return await conversation_process_start(context(turn), workflow_id=workflow_id)
    first, second = await asyncio.gather(launch(), launch())
    assert first["run_id"] == second["run_id"] and len(requests) == 2
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ConversationProcessLink)) == 1


@pytest.mark.asyncio
async def test_cancelling_waiting_run_cannot_be_reversed_by_a_late_answer(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=True)])
    inference(monkeypatch, [assessment(), assessment({"name": "Synthetic"}, consent=False)])
    first, room = await human_turn(db, owner, "Launch my synthetic dossier.", user)
    waiting = await conversation_process_start(context(first), workflow_id=definition.code)
    from uuid import UUID
    run = await process_service.cancel_run(UUID(waiting["run_id"]))
    assert run.status == "cancelled" and run.started_at is None
    assert (await process_service.cancel_run(run.id)).status == "cancelled"
    assert await pending_process_preparations(first) == ()
    later, _ = await human_turn(db, owner, "My name is Synthetic.", user, room=room)
    result = await conversation_process_prepare(context(later), workflow_id=definition.code)
    assert result["status"] == "collecting" and result["run_id"] is None
    assert (await db.get(ProcessRun, run.id)).status == "cancelled"
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0
