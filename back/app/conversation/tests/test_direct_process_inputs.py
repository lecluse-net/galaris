"""Human structured inputs and conversational collection share one reserved run."""

# ruff: noqa: F811
from io import BytesIO

from fastapi import UploadFile
from starlette.datastructures import Headers
from PIL import Image
import pytest
from sqlalchemy import select, func

from app.agent import AgentManagementScope
from app.conversation.mcp import conversation_process_prepare, conversation_process_start
from app.conversation.process_inputs import pending_process_preparations, prepared_launch_permission
from app.conversation.tests.test_process_admission import context
from app.conversation.tests.test_process_inputs import human, human_turn, workflow, inference, assessment
from app.process.bpmn import compile_bpmn, to_bpmn
from app.process.input_editing import update_inputs, upload_input
from app.process.models import ProcessRun, ProcessStartJob, ProcessRunFile
from app.process.run_data import RunDataConflictError
from app.process.tests.test_native_bpmn import native as native, committed_native as committed_native
from app.process.values import Variable


async def setup(db, native, monkeypatch, variables):
    owner, other = native
    user = await human(db)
    owner.user_id = user.id
    definition = await workflow(owner, variables)
    turn, _ = await human_turn(db, owner, "Launch the synthetic registration.", user)
    calls = inference(monkeypatch, [assessment(single=True)], [[{"workflow_id": definition.code, "input": {"birth": "2000-02-29"}}]])
    waiting = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    run = await db.scalar(select(ProcessRun).where(ProcessRun.id == waiting["run_id"]))
    scope = AgentManagementScope(user.id, frozenset({owner.id}))
    return owner, other, definition, turn, run, scope, calls


@pytest.mark.asyncio
async def test_business_metadata_survives_definition_roundtrip(db, native):
    owner, _ = native
    declaration = Variable(name="birth", label="Beneficiary birth date", description="The beneficiary's date, not the requester's.", type="date", nullable=False)
    definition = await workflow(owner, [declaration])
    from app.process.native_definitions import read
    saved = await read(definition.code, owner.id)
    graph = compile_bpmn(saved["xml"])
    assert graph.variables[0] == declaration
    assert compile_bpmn(to_bpmn(graph)).variables[0] == declaration


@pytest.mark.asyncio
async def test_direct_input_is_reused_by_agent_without_extraction_but_keeps_final_scope_check(db, native, monkeypatch):
    owner, _, definition, turn, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    revision = run.data_revision
    saved = await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=revision)
    assert saved["status"] == "waiting" and saved["revision"] > revision
    pending = await pending_process_preparations(turn)
    assert "2000-02-29" in pending[0]["process_data"]
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    assert ready["input"]["birth"]["value"] == "2000-02-29" and ready["status"] == "ready"
    assert await prepared_launch_permission(turn, definition.code, {"birth": "2000-02-29"}, typed_values=False) is None
    assert len(calls) == 1
    started = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert str(started["run_id"]) == str(run.id) and len(calls) == 2
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1


@pytest.mark.asyncio
async def test_direct_start_and_retry_create_one_job_without_any_model_call(db, native, monkeypatch):
    _, _, definition, turn, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    revision = run.data_revision
    first = await update_inputs(run.id, scope, {}, expected_revision=revision, start=True)
    again = await update_inputs(run.id, scope, {}, expected_revision=revision, start=True)
    assert first == again and first["status"] == "queued" and len(calls) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1
    assert await pending_process_preparations(turn) == ()
    receipt = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    assert receipt["run_status"] == "queued" and receipt["input"]["birth"]["value"] == "2000-02-29"
    with pytest.raises(RunDataConflictError):
        await update_inputs(run.id, scope, {"birth": "2001-01-01"}, expected_revision=revision, start=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("values", [{"birth": "2001-02-29"}, {"birth": None}, {"undeclared": "Synthetic"}])
async def test_invalid_direct_input_cannot_mutate_or_launch(db, native, monkeypatch, values):
    _, _, _, _, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    revision = run.data_revision
    with pytest.raises(ValueError):
        await update_inputs(run.id, scope, values, expected_revision=revision, start=True)
    assert run.data_revision == revision and run.input == {} and run.status == "waiting" and len(calls) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 0


@pytest.mark.asyncio
async def test_direct_input_checks_parent_agent_scope_and_stale_revision(db, native, monkeypatch):
    _, other, _, _, run, scope, _ = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    with pytest.raises(PermissionError):
        await update_inputs(run.id, AgentManagementScope(scope.user_id, frozenset({other.id})), {}, expected_revision=run.data_revision)
    revision = run.data_revision
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=revision)
    with pytest.raises(RunDataConflictError):
        await update_inputs(run.id, scope, {"birth": "2001-01-01"}, expected_revision=revision)
    assert run.data["birth"]["value"] == "2000-02-29"


@pytest.mark.asyncio
async def test_upload_assigns_real_run_owned_file_and_no_llm(db, native, monkeypatch):
    _, _, _, _, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="portrait", type="File", nullable=False, mime_type="image/*")])
    picture = BytesIO(); Image.new("RGB", (8, 8), "white").save(picture, format="PNG"); picture.seek(0)
    upload = UploadFile(picture, filename="Synthetic.png", headers=Headers({"content-type": "image/png"}))
    saved = await upload_input(run.id, scope, "portrait", upload, expected_revision=run.data_revision)
    uri = saved["data"]["portrait"]["value"]
    assert uri.startswith(f"galaris://processes/runs/{run.id}/attachments/")
    assert await db.scalar(select(func.count()).select_from(ProcessRunFile).where(ProcessRunFile.uri == uri)) == 1
    assert len(calls) == 1 and run.status == "waiting"


@pytest.mark.asyncio
async def test_input_port_rejects_stale_collector_and_stale_release_after_direct_correction(db, native, monkeypatch):
    from app.process.facade import sync_input_run, start_input_run
    owner, _, definition, _, run, scope, _ = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    revision = run.data_revision
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=revision)
    with pytest.raises(RunDataConflictError):
        await sync_input_run(agent_id=owner.id, workflow_id=definition.code, invocation_key="synthetic-stale",
            values={}, missing=["birth"], issues={}, question="", identity=run.id, expected_revision=revision)
    with pytest.raises(RunDataConflictError):
        await start_input_run(owner.id, run.id, {"birth": {"type": "date", "value": "2001-03-01"}}, typed_values=True, expected_revision=revision)
    assert run.input["birth"]["value"] == "2000-02-29" and run.status == "waiting"


@pytest.mark.asyncio
async def test_direct_contribution_keeps_progress_when_another_saved_resource_disappears(db, native, monkeypatch):
    from app.file_share import ResourceContext, resource_create
    from app.file_share.managed_files import delete_managed_file
    from uuid import UUID
    owner, _, _, _, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False),
        Variable(name="scan", type="File", nullable=False)])
    resources = ResourceContext(agent_id=owner.id, runtime="internal")
    scan = await resource_create(resources, "file://", b"Synthetic", name="Synthetic.txt")
    await update_inputs(run.id, scope, {"scan": scan.uri}, expected_revision=run.data_revision)
    await delete_managed_file(resources, UUID(scan.uri.removeprefix("file://")))
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    assert run.data["birth"]["value"] == "2000-02-29"
    assert "scan" in run.engine_metadata["input_preparation"]["issues"]
    assert run.engine_metadata["input_preparation"]["status"] == "collecting"
    with pytest.raises(ValueError, match="Complete every selected input"):
        await update_inputs(run.id, scope, {}, expected_revision=run.data_revision, start=True)
    replacement = await resource_create(resources, "file://", b"Synthetic replacement", name="Synthetic.txt")
    await update_inputs(run.id, scope, {"scan": replacement.uri}, expected_revision=run.data_revision)
    assert run.engine_metadata["input_preparation"]["status"] == "ready" and len(calls) == 1


@pytest.mark.asyncio
async def test_confirming_an_unchanged_value_clears_an_earlier_dossier_validation_issue(db, native, monkeypatch):
    _, _, definition, turn, run, scope, calls = await setup(db, native, monkeypatch, [Variable(name="birth", type="date", nullable=False)])
    await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"birth": "2000-02-29"})
    invalid = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"birth": "2001-02-29"})
    assert "birth" in invalid["issues"]
    await update_inputs(run.id, scope, {"birth": "2000-02-29"}, expected_revision=run.data_revision)
    ready = await conversation_process_prepare(context(turn), workflow_id=definition.code)
    assert ready["status"] == "ready" and ready["issues"] == {} and len(calls) == 1


@pytest.mark.asyncio
async def test_input_http_requires_launch_privilege_and_correct_agent_scope(client, inference_db, committed_native):
    from core.user import UserModel
    from core.user.user_service import encrypt_password
    from core.authorize.models import Assignment, Role, Privilege
    from app.process.facade import sync_input_run
    from uuid import uuid4
    db = inference_db
    owner, other = committed_native
    definition = await workflow(owner, [Variable(name="birth", type="date", nullable=False)])
    run = await sync_input_run(agent_id=owner.id, workflow_id=definition.code, invocation_key="synthetic-http",
        values={}, missing=["birth"], issues={}, question="")
    identity, revision = str(run.id), run.data_revision
    for privileges, agent, expected_status in [(["PROCESS_READ"], owner, 403), (["PROCESS_LAUNCH"], other, 403), (["PROCESS_LAUNCH"], owner, 200)]:
        user = UserModel(email=f"synthetic-{uuid4().hex}@example.com", hashed_password=encrypt_password("synthetic-password"), is_active=True)
        rights = list(await db.scalars(select(Privilege).where(Privilege.code.in_(privileges))))
        role = Role(code=f"synthetic-{uuid4().hex}", privileges=rights)
        db.add_all([user, role]); await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        agent.user_id = user.id
        await db.commit()
        login = await client.post("/api/auth/login-json", json={"email": user.email, "password": "synthetic-password"})
        assert login.status_code == 200
        response = await client.patch(f"/api/processes/internal/runs/{identity}/inputs",
            headers={"Authorization": f"Bearer {login.json()['access_token']}"},
            json={"values": {"birth": "2000-02-29"}, "expected_revision": revision})
        assert response.status_code == expected_status, response.text
