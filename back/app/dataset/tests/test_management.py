"""Sharing, usage visibility and deletion use live resource permissions."""

from uuid import uuid4
import pytest
from sqlalchemy import select

from app.agent import AgentManagementScope
from app.dataset import service, sharing, usage
from app.dataset.models import DatasetRevision
from app.document import document_service
from app.document import DocumentSharingLevelUpdate, find_dataset_document_usages
from app.llm.facade import find_dataset_agent_usages
from app.llm.models import LLMCall
from app.process.facade import find_dataset_run_usages
from app.process.models import ProcessDefinition, ProcessRun
from app.tools import ToolModel
from core.team import TeamModel, TeamUserModel
from core.user import HumanActor, UserModel
from core.authorize import Assignment, Privilege
from core.authorize.models import Role


@pytest.mark.asyncio
async def test_document_sharing_contract_is_atomic_and_does_not_give_editors_ownership(db, agents):
    owner, other = agents
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    reader = UserModel(email=f"dataset-reader-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    member = UserModel(email=f"dataset-member-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
    team = TeamModel(name="Synthetic Dataset collaborators")
    db.add_all([reader, member, team]); await db.flush()
    db.add(TeamUserModel(team_id=team.id, user_id=member.id)); await db.flush()
    dataset = await service.create(owner.id, title="Synthetic shared data", content='{"kept":false}')
    initial = await sharing.read(dataset.id, scope)
    assert initial.owner.kind == "agent" and initial.owner.id == owner.id
    assert initial.level == "private" and initial.can_manage
    update = DocumentSharingLevelUpdate(level="groups", expected_lock_version=initial.lock_version,
        grants=[{"kind": "team", "id": team.id, "can_write": False},
                {"kind": "agent", "id": other.id, "can_write": True},
                {"kind": "user", "id": reader.id, "can_write": False}])
    changed = await sharing.update(dataset.id, scope, update)
    assert changed.level == "groups" and changed.lock_version == initial.lock_version + 1
    assert dataset.content == '{"kept":false}' and dataset.revision == 1
    assert (await service.record(dataset.id, other.id, write=True)).id == dataset.id
    human_state = await sharing.read(dataset.id, HumanActor(reader.id))
    assert not human_state.can_manage and human_state.options == []
    assert (await service.record(dataset.id, HumanActor(member.id))).id == dataset.id
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(dataset.id, HumanActor(member.id), write=True)
    with pytest.raises((service.DatasetNotFoundError, service.DatasetPermissionError)):
        await sharing.update(dataset.id, other.id, update.model_copy(update={"expected_lock_version": changed.lock_version}))
    with pytest.raises(service.DatasetConflictError):
        await sharing.update(dataset.id, scope, update)
    with pytest.raises(ValueError):
        await sharing.update(dataset.id, scope, DocumentSharingLevelUpdate(level="private", grants=update.grants, expected_lock_version=changed.lock_version))
    assert (await sharing.read(dataset.id, scope)).model_dump() == changed.model_dump()
    public = await sharing.update(dataset.id, scope, DocumentSharingLevelUpdate(level="public", can_write=False,
        grants=[], expected_lock_version=changed.lock_version))
    assert public.level == "public" and not public.can_write and public.grants == []
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(dataset.id, other.id, write=True)
    private = await sharing.update(dataset.id, scope, DocumentSharingLevelUpdate(level="private", grants=[], expected_lock_version=public.lock_version))
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(dataset.id, other.id)
    with pytest.raises(service.DatasetConflictError):
        await service.remove(dataset.id, scope, expected_lock_version=private.lock_version - 1)
    dataset.read_only = True; await db.flush()
    assert not (await sharing.read(dataset.id, scope)).can_manage
    with pytest.raises(service.DatasetNotFoundError):
        await sharing.update(dataset.id, scope, DocumentSharingLevelUpdate(level="public", grants=[], expected_lock_version=private.lock_version))
    dataset.read_only = False; await db.flush()
    await service.remove(dataset.id, scope, expected_lock_version=dataset.lock_version)
    with pytest.raises(service.DatasetNotFoundError):
        await service.record(dataset.id, scope)
    assert await db.scalar(select(DatasetRevision.content).where(DatasetRevision.dataset_id == dataset.id)) == '{"kept":false}'


@pytest.mark.asyncio
@pytest.mark.parametrize("reference_source", ["snapshot", "data", "files"])
async def test_dataset_usages_find_current_documents_processes_and_agent_traces_without_leaking_private_sources(db, agents, memory_storage, monkeypatch, reference_source):
    owner, other = agents
    scope = AgentManagementScope(user_id=owner.user_id, agent_ids=frozenset({owner.id}))
    privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(["MEMORY_ACCESS", "PROCESS_READ", "AGENT_ACCESS"]))))
    assert len(privileges) == 3
    role = Role(code=f"synthetic-dataset-sources-{uuid4().hex}", privileges=privileges)
    db.add(role); await db.flush()
    assignment = Assignment(user_id=owner.user_id, role_id=role.id)
    db.add(assignment); await db.flush()
    dataset = await service.create(owner.id, title="Synthetic dependency target")
    uri = f"data://{dataset.id}"
    for agent, label in [(owner, "Synthetic visible page"), (owner, "Synthetic other page"), (other, "Synthetic hidden page")]:
        await document_service.create_document(owner_agent_id=agent.id, title=label, task_id=None,
            content=f'<form data-dataset="{uri}"><p>Synthetic Dataset application</p></form>')
    tool = await db.scalar(select(ToolModel).where(ToolModel.code == "galaris"))
    definition = ProcessDefinition(agent_id=owner.id, code="synthetic_" + uuid4().hex, tool_id=tool.id, engine_process_id=f"synthetic-{uuid4()}", label="Synthetic workflow")
    db.add(definition); await db.flush()
    run = ProcessRun(process_id=definition.id, launcher_agent_id=owner.id, engine_code="galaris", correlation_id=str(uuid4()),
        callback_token=str(uuid4()),
        launch_snapshot={"input": {"dataset": {"type": "Dataset", "value": uri}}} if reference_source == "snapshot" else {},
        data={"dataset": {"type": "Dataset", "value": uri}} if reference_source == "data" else {})
    db.add(run)
    if reference_source == "files":
        from app.process.models import ProcessRunFile
        await db.flush()
        db.add(ProcessRunFile(run_id=run.id, uri=uri))
    for agent in (owner, other):
        db.add(LLMCall(agent_id=agent.id, tool_calls=[{"name": "file_read", "arguments": {"uri": uri}}]))
    await db.flush()
    monkeypatch.setattr(usage, "_sources", {})
    usage.register_dataset_usage_source("documents", "documents", find_dataset_document_usages)
    usage.register_dataset_usage_source("processes", "runs", find_dataset_run_usages)
    usage.register_dataset_usage_source("agents", "agents", find_dataset_agent_usages)
    first = await usage.list_usages(dataset.id, scope, kind="documents", page_size=1)
    second = await usage.list_usages(dataset.id, scope, kind="documents", page=2, page_size=1)
    assert first["total"] == second["total"] == 2
    assert {first["items"][0]["label"], second["items"][0]["label"]} == {"Synthetic visible page", "Synthetic other page"}
    processes = await usage.list_usages(dataset.id, scope, kind="processes")
    assert processes["total"] == 1 and processes["items"][0]["url"] == f"/process/internal/run/{run.id}"
    observed = await usage.list_usages(dataset.id, scope, kind="agents")
    assert observed["total"] == 1 and observed["items"][0]["id"] == f"agent:{owner.id}"
    with pytest.raises(service.DatasetNotFoundError):
        await usage.list_usages(dataset.id, AgentManagementScope(user_id=other.user_id, agent_ids=frozenset({other.id})), kind="documents")
    await db.delete(assignment); await db.flush()
    for kind in ("documents", "processes", "agents"):
        assert (await usage.list_usages(dataset.id, scope, kind=kind))["total"] == 0
