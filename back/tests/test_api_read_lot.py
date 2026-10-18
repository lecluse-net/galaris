"""Synthetic measurements and consumer contracts for lightweight API projections."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import event, inspect, select

from app.agent import AgentManagementScope
from app.agent.models import Agent, Title
from app.dataset.compatibility import LegacyDatasetAdapter
from app.dataset.models import Dataset, DatasetRevision
from app.incident import router as incidents
from app.incident import service as incident_service
from app.incident.models import FailureIncident, FailureIncidentTrace, FailurePattern
from app.lab import evaluation_service as evaluation
from app.lab import process_evaluation
from app.lab.models import LabTask
from app.lab.process_evaluation_models import LabProcessCampaign, LabProcessCase
from app.llm import llm_service
from app.llm.provider_models import LLM, LLMProvider
from app.memory import document_service, MemoryNotFoundError
from app.memory.tests.conftest import memory_storage as memory_storage
from app.process import native_definitions as definitions
from app.process.bpmn import to_bpmn
from app.process.models import ProcessDefinition, ProcessDefinitionRevision
from app.process.tests.test_native_bpmn import graph
from app.skill import learning_service, skill_service, storage
from app.skill import router as skills
from app.skill.models import AgentSkill, AgentSkillCategory, LearnedSkill, Skill, SkillCategory
from app.task import Task, TaskStatus
from app.tools.models import Tool


@pytest_asyncio.fixture
async def read_actors(db):
    title = Title(label="Synthetic API reads", gender="N")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"synthetic-api-read-{index}", first_name="Synthetic",
                    last_name=str(index), avatar=b"a" * 100_000) for index in range(2)]
    db.add_all(agents)
    await db.flush()
    return agents


@asynccontextmanager
async def measured(db, name, fields):
    """Count actual SELECTs, loaded objects and omitted payload bytes on a cold session."""
    db.expunge_all()
    connection = await db.connection()
    report = {"queries": 0, "rows": 0, "bytes": 0}

    def statement(_connection, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper().startswith(("SELECT", "WITH")):
            report["queries"] += 1

    def loaded(_session, instance):
        for model, names in fields.items():
            if not isinstance(instance, model):
                continue
            report["rows"] += 1
            for field in names:
                if field in inspect(instance).unloaded:
                    continue
                value = getattr(instance, field)
                if value is not None:
                    payload = value if isinstance(value, (str, bytes)) else json.dumps(value)
                    report["bytes"] += len(payload if isinstance(payload, bytes) else payload.encode())

    event.listen(connection.sync_connection, "before_cursor_execute", statement)
    event.listen(db.sync_session, "loaded_as_persistent", loaded)
    try:
        yield report
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", statement)
        event.remove(db.sync_session, "loaded_as_persistent", loaded)
        destination = Path(__file__).resolve().parents[2] / f"artifacts/api-read-lot-{name}.json"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(report, indent=2) + "\n")


@pytest.mark.asyncio
async def test_legacy_history_keeps_utf8_hashes_and_explicit_content_reads(db, read_actors):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    source = Dataset(owner_agent_id=owner_id, title="Synthetic legacy history", content="[]", revision=41)
    db.add(source)
    await db.flush()
    identity = source.id
    now = datetime.now(timezone.utc)
    values = [json.dumps({"synthetic": index, "unicode": "é🙂" * 5000}, ensure_ascii=False) + "\n" for index in range(41)]
    db.add_all([DatasetRevision(dataset_id=identity, revision=index + 1, content=value,
                                author_agent_id=owner_id, created_at=now + timedelta(seconds=index))
                for index, value in enumerate(values)])
    await db.commit()
    adapter = LegacyDatasetAdapter()
    async with measured(db, "legacy-history", {DatasetRevision: ("content",)}) as report:
        result = await adapter.history(identity, owner_id, 50, 0)
    assert result["total"] == 41 and not result["has_more"]
    assert [item["revision"] for item in result["items"]] == list(range(41, 0, -1))
    assert [item["content_hash"] for item in result["items"]] == [hashlib.sha256(value.encode()).hexdigest() for value in reversed(values)]
    assert all(item["media_type"] == "application/json" and item["author_agent_id"] == owner_id for item in result["items"])
    assert (await adapter.history(identity, owner_id, 10, 10))["items"] == result["items"][10:20]
    assert (await adapter.history(identity, owner_id, 500, 500))["items"] == []
    with pytest.raises(MemoryNotFoundError):
        await adapter.history(identity, peer_id, 50, 0)
    assert (await adapter.read(identity, owner_id, revision=1))["content"] == values[0]
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_process_history_does_not_load_current_xml_but_detail_does(db, read_actors):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    xml = to_bpmn(graph("Synthetic activity " * 6000), "synthetic_history")
    tool_id = await db.scalar(select(Tool.id).where(Tool.code == "galaris"))
    record = ProcessDefinition(agent_id=owner_id, tool_id=tool_id, engine_process_id="synthetic_history",
                               code="synthetic_history", label="Synthetic Process", bpmn_xml=xml, revision=3)
    db.add(record)
    await db.flush()
    db.add_all([ProcessDefinitionRevision(process_id=record.id, revision=index, bpmn_xml=xml,
                                         author_agent_id=owner_id) for index in range(1, 4)])
    await db.commit()
    async with measured(db, "process-history", {ProcessDefinition: ("bpmn_xml",), ProcessDefinitionRevision: ("bpmn_xml",)}) as report:
        result = await definitions.history("synthetic_history", owner_id, limit=2, exclude_current=True)
    assert result["total"] == 2 and [item["revision"] for item in result["items"]] == [2, 1]
    assert not result["has_more"]
    assert (await definitions.history("synthetic_history", owner_id, limit=1, offset=1))["items"] == result["items"][:1]
    with pytest.raises(PermissionError):
        await definitions.history("synthetic_history", peer_id)
    assert (await definitions.get("synthetic_history", owner_id))[0].bpmn_xml == xml
    assert (await definitions.revision_detail("synthetic_history", owner_id, 1))["detail"]["content"] == xml
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_skill_catalogue_leaves_the_assignment_matrix_to_authorization_reads(db, read_actors, tmp_path, monkeypatch):
    owner, peer = read_actors
    owner_id = owner.id
    root = tmp_path / "skills"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(root))
    category = SkillCategory(label="Synthetic catalogue category")
    db.add(category)
    await db.flush()
    category_id = category.id
    records = [Skill(code=f"synthetic-catalogue-{index:02d}", label=f"Synthetic catalogue {index:02d}", category_id=category_id)
               for index in range(41)]
    db.add_all(records)
    await db.flush()
    ids = [row.id for row in records]
    for row in records:
        directory = root / row.code
        directory.mkdir(parents=True)
        (directory / "SKILL.md").write_text(f"---\nname: {row.code}\ndescription: Synthetic procedure.\n---\n")
        db.add_all([AgentSkill(agent_id=agent.id, skill_id=row.id, active=True) for agent in (owner, peer)])
    db.add_all([AgentSkillCategory(agent_id=agent.id, category_id=category_id, active=True) for agent in (owner, peer)])
    await db.commit()
    async with measured(db, "skill-catalogue", {AgentSkill: (), AgentSkillCategory: ()}) as report:
        result = [item for item in await skills.list_skills() if item.id in ids]
    assert [item.id for item in result] == ids
    assert all(item.category_label == "Synthetic catalogue category" and item.valid and item.available for item in result)
    assert all(item.description == "Synthetic procedure." for item in result)
    authorizations = await skill_service.list_authorizations(agent_id=owner_id, skill_id=ids[0])
    assert authorizations[0].agent_state == "enabled" and authorizations[0].category_state == "enabled"
    category = await db.get(SkillCategory, category_id)
    category.soft_delete()
    await db.commit()
    db.expunge_all()
    assert next(item for item in await skills.list_skills() if item.id == ids[0]).category_label is None
    assert report["queries"] == 1 and report["rows"] == 0, report


@pytest.mark.asyncio
async def test_learned_skill_list_preserves_metadata_scope_and_full_detail(db, read_actors):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    now = datetime.now(timezone.utc)
    rows = [LearnedSkill(agent_id=owner_id, code=f"synthetic-learned-{index:02d}", label=f"Synthetic learned {index}",
                         description="Synthetic description", markdown="Synthetic procedure.\n" * 2500,
                         evidence_count=3, score=.95, suspended=index % 2 == 0, updated_at=now - timedelta(seconds=index))
            for index in range(41)]
    db.add_all([*rows, LearnedSkill(agent_id=peer_id, code="synthetic-hidden", label="Synthetic hidden",
                                    description="Synthetic hidden", markdown="Synthetic private procedure")])
    await db.commit()
    ids, markdown = [row.id for row in rows], rows[0].markdown
    async with measured(db, "learned-list", {LearnedSkill: ("markdown",)}) as report:
        items, total = await learning_service.list_records(agent_id=None, page=1, page_size=50, agent_ids=[owner_id])
        public = [skills._learned_public(item) for item in items]
    assert total == 41 and [item.id for item in public] == ids
    assert all(item.description == "Synthetic description" and item.evidence_count == 3 and item.score == .95 for item in public)
    assert [item.suspended for item in public] == [index % 2 == 0 for index in range(41)]
    assert (await learning_service.list_records(agent_id=None, page=1, page_size=500, agent_ids=[])) == ([], 0)
    assert (await learning_service.list_records(agent_id=peer_id, page=1, page_size=500, agent_ids=[owner_id])) == ([], 0)
    assert (await learning_service.get_record(ids[0])).markdown == markdown
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_incident_list_reads_only_the_pattern_status_and_counter(db, read_actors):
    owner, _peer = read_actors
    owner_id = owner.id
    now = datetime.now(timezone.utc)
    patterns = [FailurePattern(fingerprint=f"synthetic-list-{index}", kind="tool", category="synthetic",
                               title=f"Synthetic pattern {index}", status="triaged", occurrence_count=index + 1,
                               diagnosis="Synthetic diagnosis. " * 5000, root_cause="Synthetic cause. " * 5000,
                               first_seen_at=now, last_seen_at=now) for index in range(41)]
    db.add_all(patterns)
    await db.flush()
    rows = [FailureIncident(pattern_id=pattern.id, idempotency_key=f"synthetic-list-{index}", kind="tool",
                            category="synthetic", phase="execute", severity="error", error_type="SyntheticError",
                            error_message=f"Synthetic failure {index}", agent_id=owner_id,
                            occurred_at=now - timedelta(seconds=index)) for index, pattern in enumerate(patterns)]
    db.add_all(rows)
    await db.flush()
    db.add(FailureIncidentTrace(incident_id=rows[0].id, payload={}, content_hash="0" * 64, byte_size=2))
    await db.commit()
    expected = [incidents._incident_read(row, pattern) for row, pattern in zip(rows, patterns)]
    identity = rows[0].id
    async with measured(db, "incident-list", {FailurePattern: ("diagnosis", "root_cause")}) as report:
        items, total = await incident_service.list_incidents(page=1, page_size=50, agent_ids=[owner_id])
        public = [incidents._incident_read(row, pattern) for row, pattern in items]
    assert total == 41 and public == expected
    assert (await incident_service.list_incidents(page=1, page_size=10, search="failure 40", agent_ids=[owner_id]))[1] == 1
    assert (await incident_service.list_incidents(page=1, page_size=500, agent_ids=[]))[1] == 0
    assert (await incident_service.get_incident(identity))[1].diagnosis == "Synthetic diagnosis. " * 5000
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_llm_capability_filter_runs_before_materialization(db):
    provider = LLMProvider(name="Synthetic capability catalogue", base_url="https://models.example.com")
    db.add(provider)
    await db.flush()
    provider_id = provider.id
    resources = [LLM(llm_provider_id=provider_id, code=f"synthetic-capability-{index}", label=f"Synthetic model {index:02d}",
                     llm_name=f"synthetic/model-{index}", service_capabilities=["decision", "chat"] if index == 0 else ["speech"],
                     pricing={"synthetic": "x" * 30000}) for index in range(41)]
    db.add_all(resources)
    await db.commit()
    wanted = resources[0].id
    async with measured(db, "llm-filter", {LLM: ("pricing",)}) as report:
        result = await llm_service.list_llms(provider_id=provider_id, capability="chat")
    assert [row.id for row in result] == [wanted]
    assert result[0].provider.name == "Synthetic capability catalogue"
    assert [row.id for row in await llm_service.list_llms(provider_id=provider_id, capability="decision")] == [wanted]
    assert len(await llm_service.list_llms(provider_id=provider_id, capability="speech")) == 40
    assert await llm_service.list_llms(provider_id=provider_id, capability="missing") == []
    assert len(await llm_service.list_llms(provider_id=provider_id)) == 41
    assert report["rows"] == 1, report


@pytest.mark.asyncio
@pytest.mark.parametrize("listing", ["candidates", "references"])
async def test_lab_task_lists_keep_summaries_without_task_payloads_or_agent_avatars(db, read_actors, listing):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    now = datetime.now(timezone.utc)
    tasks = [Task(agent=owner, label=f"Synthetic Task {index:02d}", objective=f"<p>Synthetic objective {index}</p>",
                  status=TaskStatus.SUCCESS, updated_at=now - timedelta(seconds=index), data={"synthetic": "x" * 100_000},
                  execution_result={"synthetic": "y" * 100_000}) for index in range(41)]
    peer_task = Task(agent=peer, label="Synthetic peer Task", status=TaskStatus.SUCCESS)
    removed = Task(agent=owner, label="Synthetic deleted Task", status=TaskStatus.SUCCESS)
    db.add_all([*tasks, peer_task, removed])
    await db.flush()
    expected = [evaluation.task_summary(task) for task in tasks]
    removed.soft_delete()
    selected = tasks[::2]
    db.add_all([LabTask(task_id=task.id) for task in [*selected, peer_task, removed]])
    await db.commit()
    async with measured(db, f"lab-{listing}", {Task: ("data", "execution_result"), Agent: ("avatar",)}) as report:
        if listing == "candidates":
            result = await evaluation.list_candidates(agent_ids=[owner_id], limit=500)
            assert result == expected[1::2]
        else:
            result = await evaluation.list_tasks(agent_ids=[owner_id])
            assert {row.task_id: row.task for row in result} == {
                **{row.task_id: row for row in expected[::2]}, peer_task.id: None, removed.id: None,
            }
    assert (await evaluation.list_candidates(agent_ids=[peer_id], limit=500)) == []
    assert await evaluation.list_candidates(agent_ids=[], limit=500) == []
    assert (await evaluation.get_task(tasks[0].id)).data == {"synthetic": "x" * 100_000}
    assert report["queries"] <= (1 if listing == "candidates" else 2) and report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_process_campaign_inspection_leaves_worker_inputs_unloaded(db, read_actors, memory_storage):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    document = await document_service.create_document(owner_agent_id=owner_id, title="Synthetic campaign reference",
                                                      task_id=None, content="<p>Synthetic reference</p>")
    campaign = LabProcessCampaign(owner_agent_id=owner_id, dataset_document_id=document.id,
                                   process_code="synthetic_campaign", title="Synthetic campaign", invocation_key="synthetic",
                                   fingerprint="s" * 64)
    db.add(campaign)
    await db.flush()
    identity = campaign.id
    cases = [LabProcessCase(campaign_id=identity, position=index, input={"synthetic": "x" * 30000},
                            expected={"synthetic": "y" * 30000}, files=[{"uri": "https://example.com/" + "f" * 2000}],
                            evidence={"synthetic": index}) for index in range(41)]
    db.add_all(cases)
    await db.commit()
    ids = [case.id for case in cases]
    async with measured(db, "process-campaign", {LabProcessCase: ("input", "expected", "files")}) as report:
        result = await process_evaluation.inspect_campaign(identity, owner_id)
    assert result["total"] == 41 and [item["id"] for item in result["items"]] == [str(value) for value in ids]
    assert [item["evidence"] for item in result["items"]] == [{"synthetic": index} for index in range(41)]
    assert (await process_evaluation.inspect_campaign(identity, owner_id, page=2, page_size=10))["items"] == result["items"][10:20]
    with pytest.raises(PermissionError):
        await process_evaluation.inspect_campaign(identity, peer_id)
    assert (await db.scalar(select(LabProcessCase).where(LabProcessCase.id == ids[0]))).input == {"synthetic": "x" * 30000}
    assert report["bytes"] == 0, report
