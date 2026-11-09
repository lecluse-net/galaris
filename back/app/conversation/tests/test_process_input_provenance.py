"""Input audit must add no model context, implicit ORM load or source authority."""

# ruff: noqa: F811
import json
from uuid import UUID

import pytest
from sqlalchemy import select, func, inspect
from sqlalchemy.exc import InvalidRequestError

from app.agent import AgentManagementScope
from app.conversation.mcp import conversation_process_prepare
from app.conversation.models import ConversationRound
from app.conversation.tests.test_direct_process_inputs import setup
from app.conversation.tests.test_process_admission import context
from app.file_share import ResourceContext, resource_create, resource_read
from app.file_share.managed_files import delete_managed_file
from app.image.mcp import image_from_pdf
from app.image.tests.test_pdf_conversion import pdf_bytes
from app.process.facade import read_input_provenance
from app.process.input_editing import update_inputs
from app.process.input_provenance import PROVENANCE_EVENT, record_inputs
from app.process.models import ProcessRun, ProcessRunEvent
from app.process.native_runs import inspect_run
from app.process.tests.test_native_bpmn import native as native, committed_native as committed_native
from app.process.values import Variable
from app.tools import McpToolContext
from tests.sql_reads import measured_reads


async def stored(db, run, name):
    return await db.scalar(select(ProcessRun.input_provenance[name]).where(ProcessRun.id == run.id))


@pytest.mark.asyncio
async def test_provenance_is_deferred_and_absent_from_normal_run_tools_context_and_events(db, native, monkeypatch):
    owner, _, definition, turn, run, _, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"birth": "2000-02-29"})
    origin = await stored(db, run, "birth")
    assert origin["kind"] == "agent" and origin["reference"] == f"galaris://text/{turn.round_id}"
    assert "2000-02-29" not in json.dumps(origin) and len(json.dumps(origin).encode()) < 400
    db.expire(run, ["input_provenance"])
    assert "input_provenance" in inspect(run).unloaded
    with pytest.raises(InvalidRequestError):
        _ = run.input_provenance
    async with measured_reads(db, "normal-run-with-provenance") as reads:
        snapshot = await inspect_run(run.id, owner.id)
    assert "input_provenance" not in reads.result_columns
    assert origin["value_sha256"] not in json.dumps(snapshot)
    assert PROVENANCE_EVENT not in json.dumps(snapshot)
    assert "provenance" not in json.dumps(ready)
    dossier = (await db.get(ConversationRound, turn.round_id)).process_preparations[definition.code]
    assert origin["value_sha256"] not in json.dumps(dossier)
    assert len(calls) == 1
    # Cache/retries must not add another audit row or model request.
    count = await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.event_type == PROVENANCE_EVENT))
    assert await conversation_process_prepare(context(turn), workflow_id=definition.code) == ready
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.event_type == PROVENANCE_EVENT)) == count


@pytest.mark.asyncio
async def test_human_corrections_have_paginated_history_without_copying_values(db, native, monkeypatch):
    _, _, _, _, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    first = await read_input_provenance(run.id, scope, "birth")
    assert first["current"]["kind"] == "human" and first["current"]["actor_user_id"] == scope.user_id
    await update_inputs(run.id, scope, {"birth": "2001-03-01"}, expected_revision=run.data_revision)
    second = await read_input_provenance(run.id, scope, "birth")
    assert first["current"]["value_sha256"] != second["current"]["value_sha256"]
    page = await read_input_provenance(run.id, scope, "birth", history=True, page_size=1)
    assert len(page["entries"]) == 1 and page["next_before"] is not None
    previous = await read_input_provenance(run.id, scope, "birth", history=True, page_size=1, before=page["next_before"])
    assert previous["entries"][0]["origin"]["value_sha256"] == first["current"]["value_sha256"]
    assert "2001-03-01" not in json.dumps(page) and len(calls) == 1
    # Reconfirming unchanged data from the same origin is an audit no-op.
    count = await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.event_type == PROVENANCE_EVENT))
    await update_inputs(run.id, scope, {"birth": "2001-03-01"}, expected_revision=run.data_revision)
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.event_type == PROVENANCE_EVENT)) == count


@pytest.mark.asyncio
async def test_conversion_trace_reuses_trusted_receipts_and_rechecks_source_access(db, native, monkeypatch):
    owner, other, _, _, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="scan", type="File", nullable=False, mime_type="image/*")])
    resources = ResourceContext(agent_id=owner.id, runtime="internal")
    pdf = await resource_create(resources, "file://", pdf_bytes(), name="Synthetic.pdf")
    converted = await image_from_pdf(McpToolContext(agent_id=owner.id, runtime="internal"), pdf.uri, "file://", page=2)
    await update_inputs(run.id, scope, {"scan": converted["uri"]}, expected_revision=run.data_revision)
    origin = (await read_input_provenance(run.id, owner.id, "scan"))["current"]
    assert origin["resource"]["conversion"]["method"] == "pdf_page"
    assert origin["resource"]["conversion"]["page"] == 2
    assert origin["resource"]["conversion"]["source"]["reference"] == pdf.uri
    with pytest.raises(PermissionError):
        await read_input_provenance(run.id, other.id, "scan")
    with pytest.raises(PermissionError):
        await read_input_provenance(run.id, AgentManagementScope(scope.user_id, frozenset({other.id})), "scan")
    await delete_managed_file(resources, UUID(pdf.uri.removeprefix("file://")))
    hidden = (await read_input_provenance(run.id, owner.id, "scan"))["current"]
    assert hidden["resource"]["conversion"]["source"] == {"accessible": False}
    uri = f"galaris://processes/runs/{run.id}/input-provenance/scan"
    explicit = await resource_read(resources, uri, max_chars=4000)
    assert json.loads(explicit.content)["current"]["kind"] == "human" and len(calls) == 1


@pytest.mark.asyncio
async def test_audit_writes_roll_back_with_the_input_transaction(db, native, monkeypatch):
    owner, _, _, _, run, _, _ = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    identity, owner_identity = run.id, owner.id
    await record_inputs(run, {"birth": {"type": "date", "value": "2000-02-29"}}, origins={"birth": {"kind": "human"}})
    await db.flush()
    await db.rollback()
    assert await db.scalar(select(ProcessRun.input_provenance).where(ProcessRun.id == identity)) == {}
    assert await db.scalar(select(func.count()).select_from(ProcessRunEvent).where(ProcessRunEvent.run_id == identity,
        ProcessRunEvent.event_type == PROVENANCE_EVENT)) == 0
    # Old runs remain readable without invented retrospective sources.
    assert (await read_input_provenance(identity, owner_identity, "birth"))["current"] is None


@pytest.mark.asyncio
async def test_even_a_large_audit_does_not_change_the_input_assessment_prompt(db, native, monkeypatch):
    from app.conversation.process_inputs import _assess
    from app.conversation.tests.test_process_inputs import inference, assessment
    owner, _, _, turn, run, _, _ = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, ToolCallPart, SystemPromptPart, UserPromptPart
    from app.llm import structured_service
    from unittest.mock import AsyncMock
    inference(monkeypatch, [])
    prompts = []
    def respond(messages, info):
        prompts.append([part.content for message in messages for part in message.parts if isinstance(part, (SystemPromptPart, UserPromptPart))])
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, assessment())])
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=FunctionModel(respond)))
    contract = {"declarations": [{"name": "birth", "type": "date", "nullable": False}], "values": {}, "missing": ["birth"]}
    await _assess(turn, contract, None, {}, [])
    run.input_provenance = {"synthetic_audit_marker": "audit-only-never-model-context" * 10_000}
    await db.commit()
    await _assess(turn, contract, None, {}, [])
    assert len(prompts) == 2 and prompts[0] == prompts[1]
    assert "synthetic_audit_marker" not in json.dumps(prompts[1])


@pytest.mark.asyncio
async def test_direct_launch_distinguishes_defaults_and_explicit_values(db, native):
    from app.conversation.tests.test_process_inputs import workflow
    from app.process import process_service
    owner, _ = native
    process = await workflow(owner, [Variable(name="count", type="int", nullable=False, default={"type": "int", "value": 0})])
    defaulted = await process_service.start_process(agent_id=owner.id, workflow_id=process.code, input_data={})
    explicit = await process_service.start_process(agent_id=owner.id, workflow_id=process.code, input_data={"count": {"type": "int", "value": 0}})
    assert (await read_input_provenance(defaulted.run_id, owner.id, "count"))["current"]["kind"] == "default"
    assert (await read_input_provenance(explicit.run_id, owner.id, "count"))["current"]["kind"] == "agent"


@pytest.mark.asyncio
async def test_external_event_with_the_same_name_remains_visible(db, native, monkeypatch):
    from app.process import process_service
    _, _, _, _, run, _, _ = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    # A frozen historical run may keep its old engine after a definition changes.
    run.engine_code = "synthetic-external"
    db.add(ProcessRunEvent(run_id=run.id, source="synthetic-external", event_type=PROVENANCE_EVENT,
        payload={"synthetic_external_event": True}))
    await db.commit()
    detail = await process_service.get_run_detail(run.id, refresh_if_stale=False)
    assert any(event.payload.get("synthetic_external_event") for event in detail.events)


@pytest.mark.asyncio
async def test_source_deadline_releases_a_cancelled_database_operation_before_retry(inference_db, committed_native, monkeypatch):
    from app.file_share import facade as sources
    from app.process.input_provenance import ProvenanceUnavailable
    db = inference_db
    owner, _, _, _, run, scope, _ = await setup(db, committed_native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    await record_inputs(run, {"birth": run.input["birth"]}, origins={"birth": {"kind": "agent", "reference": "file://synthetic-timeout"}})
    await db.commit()
    identity, agent = run.id, owner.id
    async def stalled_source(*_):
        await db.execute(select(func.pg_sleep(3)))
        return True
    monkeypatch.setattr(sources, "can_inspect_source", stalled_source)
    with pytest.raises(ProvenanceUnavailable):
        await read_input_provenance(identity, agent, "birth")
    assert await db.scalar(select(1)) == 1
    assert (await db.scalar(select(ProcessRun.input).where(ProcessRun.id == identity)))["birth"]["value"] == "2000-02-29"


@pytest.mark.asyncio
async def test_http_provenance_requires_read_privilege_and_does_not_grant_write(client, inference_db, committed_native, monkeypatch):
    from core.user import UserModel
    from core.user.user_service import encrypt_password
    from core.authorize.models import Assignment, Role, Privilege
    from uuid import uuid4
    db = inference_db
    owner, _, _, _, run, scope, _ = await setup(db, committed_native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    identity = str(run.id)
    user = await db.get(UserModel, scope.user_id)
    user.email = f"synthetic-provenance-{uuid4().hex}@example.com"
    user.hashed_password = encrypt_password("synthetic-password")
    privilege = await db.scalar(select(Privilege).where(Privilege.code == "PROCESS_READ"))
    role = Role(code=f"synthetic-{uuid4().hex}", privileges=[privilege])
    db.add(role); await db.flush()
    db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
    await db.commit()
    login = await client.post("/api/auth/login-json", json={"email": user.email, "password": "synthetic-password"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    path = f"/api/processes/internal/runs/{identity}/inputs/provenance"
    response = await client.get(path, headers=headers, params={"name": "birth"})
    assert response.status_code == 200, response.text
    assert response.json()["current"]["kind"] == "human"
    # Process read rights alone do not reveal a source from another domain.
    from app.file_share import ResourceContext, resource_create
    from app.process.input_provenance import record_inputs
    file = await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "file://", b"Synthetic", name="Synthetic.txt")
    await record_inputs(run, {"birth": run.input["birth"]}, origins={"birth": {"kind": "agent", "reference": file.uri}})
    await db.commit()
    source_hidden = await client.get(path, headers=headers, params={"name": "birth"})
    assert source_hidden.status_code == 200
    assert source_hidden.json()["current"]["accessible"] is False and "reference" not in source_hidden.json()["current"]
    assert (await client.patch(f"/api/processes/internal/runs/{identity}/inputs", headers=headers,
        json={"values": {}, "expected_revision": 1})).status_code == 403
    role.privileges = []
    await db.commit()
    assert (await client.get(path, headers=headers, params={"name": "birth"})).status_code == 403
