"""Real PostgreSQL budgets for selectors, histories and participant catalogues."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.connection import Connection, ConnectionParam
from app.conversation import ConversationRound, ConversationRoundMessage
from app.lab import dispatcher_evaluation_service as dispatcher
from app.lab import mechanism_evaluation_service as mechanisms
from app.lab.models import LabEvaluationDataset, LabEvaluationRun
from app.memory import MemoryItem
from app.messenger import Message, Room
from app.skill import resource_facade, skill_service, storage
from app.skill.models import AgentSkill, AgentSkillCategory, Skill, SkillCategory
from app.task import Task, TaskStatus
from app.tools import ToolModel
from app.topic import Topic, service as topics
from core.team import service as teams
from core.team.models import Team, TeamUser
from core.user import UserModel
from tests.test_api_read_lot import measured, read_actors as read_actors


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["catalogue", "search", "members"])
async def test_team_selectors_keep_labels_avatars_activity_and_limits(db, view):
    people = [UserModel(email=f"synthetic-selector-{index:02d}@example.com", display_name=f"Synthetic Human {index:02d}",
                        hashed_password="synthetic-password-hash", is_active=index != 0,
                        avatar_key=uuid4(), avatar_mime_type="image/png",
                        totp_secret_encrypted="synthetic-encrypted-secret",
                        recovery_code_hashes=[f"synthetic-hash-{offset}" for offset in range(10)])
              for index in range(41)]
    people[1].display_name = None
    small, large = Team(name="Synthetic small", order=0), Team(name="Synthetic large", order=1)
    db.add_all([*people, small, large])
    await db.flush()
    db.add_all([TeamUser(team_id=small.id, user_id=user.id) for user in people[:2]])
    db.add_all([TeamUser(team_id=large.id, user_id=user.id) for user in people])
    expected = [{"id": user.id, "label": user.display_name or user.email, "active": user.is_active,
                 "avatar_url": user.avatar_url} for user in people]
    small_id, large_id = small.id, large.id
    await db.commit()
    async with measured(db, f"selectors-team-{view}", {UserModel: ("hashed_password", "totp_secret_encrypted", "recovery_code_hashes")}) as report:
        if view == "catalogue":
            result = await teams.list_teams()
            by_id = {item.id: item for item in result}
            assert by_id[small_id].human_count == 2
            assert [item.model_dump() for item in by_id[small_id].human_members] == expected[:2]
            assert by_id[large_id].human_count == 41 and by_id[large_id].human_members == []
        elif view == "search":
            result = await teams.search_humans("synthetic-selector-", limit=500)
            assert [item.model_dump() for item in result] == expected
        else:
            result = await teams.team_humans(large_id)
            assert [item.model_dump() for item in result] == expected
    assert [item.id for item in await teams.search_humans("  SYNTHETIC-selector-  ", limit=10)] == [item["id"] for item in expected[:10]]
    assert await teams.search_humans("synthetic-does-not-exist") == []
    with pytest.raises(LookupError):
        await teams.team_humans(-1)
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["dispatcher", "task_analysis"])
async def test_run_lists_omit_frozen_cases_without_changing_public_runs_or_workers(db, mechanism):
    dataset = LabEvaluationDataset(mechanism=mechanism, name=f"Synthetic selector {mechanism}")
    db.add(dataset)
    await db.flush()
    now = datetime.now(timezone.utc)
    runs = [LabEvaluationRun(dataset_id=dataset.id, status="completed", phase="finished",
                              case_snapshots=[{"input": "synthetic " * 10000, "case": index}],
                              configuration_snapshot={"synthetic": index}, analysis_markdown=f"Analysis {index}",
                              total_cases=1, completed_cases=1, cost=float(index),
                              created_at=now - timedelta(seconds=index)) for index in range(41)]
    db.add_all(runs)
    await db.flush()
    deleted = LabEvaluationRun(dataset_id=dataset.id, case_snapshots=[{"hidden": True}])
    deleted.soft_delete()
    db.add(deleted)
    dataset_id, run_id = dataset.id, runs[0].id
    identities = [run.id for run in runs]
    await db.commit()

    async def listing(limit=50):
        return await dispatcher.list_runs(dataset_id, limit=limit) if mechanism == "dispatcher" else await mechanisms.list_runs(mechanism, dataset_id, limit=limit)

    async with measured(db, f"selectors-runs-{mechanism}", {LabEvaluationRun: ("case_snapshots",)}) as report:
        result = await listing()
    assert [item.id for item in result] == identities
    assert [(item.configuration_snapshot, item.analysis_markdown, item.cost) for item in result] == [({"synthetic": i}, f"Analysis {i}", float(i)) for i in range(41)]
    assert await listing(10) == result[:10]
    assert await listing(500) == result
    db.expunge_all()
    full = await db.scalar(select(LabEvaluationRun).where(LabEvaluationRun.id == run_id))
    assert full.case_snapshots == [{"input": "synthetic " * 10000, "case": 0}]
    detail = await dispatcher.get_run(run_id) if mechanism == "dispatcher" else await mechanisms.get_run(mechanism, run_id)
    assert detail is not None and detail.id == run_id and detail.results == []
    assert report["bytes"] == 0 and report["queries"] == 2, report


@pytest.mark.asyncio
async def test_dispatcher_picker_joins_only_public_task_and_agent_fields(db, read_actors):
    owner, peer = read_actors
    owner_id = owner.id
    now = datetime.now(timezone.utc)
    tasks = [Task(agent_id=owner.id, label=f"Synthetic dispatch {index}", objective=f"<p>Objective {index}</p>",
                  status=TaskStatus.SUCCESS, data={"synthetic": "x" * 50000}, execution_result={"result": "x" * 50000},
                  dispatch_result={"route": "DIRECT", "trace": "x" * 50000}, updated_at=now - timedelta(seconds=index))
             for index in range(21)]
    db.add_all([*tasks, Task(agent_id=peer.id, label="Other dispatch", dispatch_result={}), Task(agent_id=owner.id, label="No dispatch")])
    await db.flush()
    identities = [task.id for task in tasks]
    unassigned = Task(label="Synthetic unassigned", agent_id=None, dispatch_result={"route": "DIRECT"})
    deleted = Task(label="Synthetic deleted", agent_id=owner_id, dispatch_result={"route": "DIRECT"})
    deleted.soft_delete()
    db.add_all([unassigned, deleted])
    await db.flush()
    unassigned_id, deleted_id = unassigned.id, deleted.id
    await db.commit()
    async with measured(db, "selectors-dispatcher", {Task: ("data", "execution_result", "dispatch_result"), Agent: ("avatar",)}) as report:
        result = await dispatcher.list_task_candidates(agent_ids=[owner_id])
    assert [item.task_id for item in result] == identities
    assert all(item.agent_name == "Synthetic 0" and item.driver == "internal" for item in result)
    assert [item.objective for item in result] == [f"<p>Objective {index}</p>" for index in range(21)]
    assert await dispatcher.list_task_candidates(agent_ids=[]) == []
    assert [item.task_id for item in await dispatcher.list_task_candidates(search="Objective 20", agent_ids=[owner_id])] == [identities[-1]]
    assert await dispatcher.list_task_candidates(agent_ids=[owner_id], limit=10) == result[:10]
    all_items = await dispatcher.list_task_candidates(limit=500)
    orphan = next(item for item in all_items if item.task_id == unassigned_id)
    assert orphan.agent_name is None and orphan.driver is None
    assert deleted_id not in {item.task_id for item in all_items}
    assert report["queries"] == 1 and report["bytes"] == 0, report


def contact(index):
    return MemoryItem(title=f"Synthetic contact {index:02d}", provider_code="native", resource_id=f"synthetic-contact-{index}",
                      content="synthetic contact payload " * 5000, content_hash="s" * 64,
                      managed_source_kind="messenger_contact", managed_source_ref=f"synthetic-contact-{index}", source_managed=True, read_only=True,
                      metadata_={"display_name": f"  Person {index:02d}  ", "user_id": f"person-{index}", "unused": "x" * 10000})


@pytest.mark.asyncio
async def test_memory_source_picker_preserves_task_and_round_scope_search_and_order(db, read_actors):
    owner, peer = read_actors
    owner_id = owner.id
    now = datetime.now(timezone.utc)
    topic = Topic(title="Synthetic source topic")
    item = contact(1)
    db.add_all([topic, item])
    tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
    connection = Connection(agent_id=owner.id, tool_id=tool_id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(connection_id=connection.id, external_id="synthetic-source-room", label="Synthetic Room", conversation_type="text")
    db.add(room)
    await db.flush()
    tasks = [Task(agent_id=owner.id, label=f"Synthetic memory {index}", objective=f"Objective {index}", topic_id=topic.id,
                  status=TaskStatus.SUCCESS, data={"unused": "x" * 50000}, execution_result={"unused": "x" * 50000},
                  created_at=now - timedelta(seconds=2 * index)) for index in range(8)]
    rounds = [ConversationRound(room_id=room.id, topic_id=topic.id, contact_memory_item_id=item.id, status="SUCCEEDED",
                                 effective_objective=f"Round {index}", execution_result={"unused": "x" * 50000},
                                 encrypted_checkpoint="synthetic-opaque-" * 5000, created_at=now - timedelta(seconds=2 * index + 1))
              for index in range(7)]
    db.add_all([*tasks, *rounds, Task(agent_id=peer.id, label="Other source", status=TaskStatus.SUCCESS, topic_id=topic.id),
                Task(agent_id=owner.id, label="Failed source", status=TaskStatus.ERROR, topic_id=topic.id)])
    await db.flush()
    expected = sorted([(task.id, task.created_at) for task in tasks] + [(row.id, row.created_at) for row in rounds], key=lambda pair: pair[1], reverse=True)
    round_id, connection_id, room_id = rounds[-1].id, connection.id, room.id
    await db.commit()
    async with measured(db, "selectors-memory", {Task: ("data", "execution_result"), ConversationRound: ("execution_result", "encrypted_checkpoint")}) as report:
        result = await mechanisms.list_source_candidates("memory_extraction", agent_ids=[owner_id])
    assert [item.source_id for item in result] == [pair[0] for pair in expected]
    assert {item.source_kind for item in result} == {"task", "conversation_round"}
    assert all(item.label == "Messenger · Synthetic Room" for item in result if item.source_kind == "conversation_round")
    assert len(await mechanisms.list_source_candidates("memory_extraction", search="Objective 7", agent_ids=[owner_id])) == 1
    assert len(await mechanisms.list_source_candidates("memory_extraction", search="Round 6", agent_ids=[owner_id])) == 1
    assert await mechanisms.list_source_candidates("memory_extraction", agent_ids=[], limit=500) == []
    assert await mechanisms.list_source_candidates("memory_extraction", agent_ids=[owner_id], limit=10) == result[:10]
    # The picker also searches journal input when an older round has no objective.
    row = await db.get(ConversationRound, round_id)
    row.effective_objective = None
    message = Message(connection_id=connection_id, platform="synthetic", remote_message_id="synthetic-memory-fallback",
                      direction="inbound", messenger_room_id=room_id, text="  Synthetic\n journal fallback  ")
    db.add(message)
    await db.flush()
    db.add(ConversationRoundMessage(round_id=round_id, message_id=message.id, role="input", sequence=1))
    await db.commit()
    matches = await mechanisms.list_source_candidates("memory_extraction", search="journal fallback", agent_ids=[owner_id])
    assert [item.source_id for item in matches] == [round_id]
    assert matches[0].input_preview == "Synthetic journal fallback"
    assert report["queries"] == 2 and report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_topic_participants_do_not_fetch_contact_payloads_and_deduplicate(db, read_actors):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    topic = Topic(title="Synthetic participant topic")
    items = [contact(index) for index in range(21)]
    items[0].metadata_["display_name"] = " "
    items[1].metadata_ = {"unused": "x" * 10000}
    db.add_all([topic, *items])
    await db.flush()
    topic_id = topic.id
    expected = [(item.id, (str(item.metadata_.get("display_name") or "").strip() or str(item.metadata_.get("user_id") or "").strip() or item.title), str(item.metadata_.get("user_id") or "").strip()) for item in items]
    db.add_all([Task(agent_id=owner.id, label=f"Synthetic participant {index}", topic_id=topic.id, contact_memory_item_id=item.id) for index, item in enumerate(items)])
    db.add(Task(agent_id=owner.id, label="Synthetic duplicate", topic_id=topic.id, contact_memory_item_id=items[0].id))
    await db.commit()
    async with measured(db, "selectors-topic-contacts", {MemoryItem: ("memory_content", "metadata_")}) as report:
        page = await topics.list_page(skip=0, limit=50, search="Synthetic participant", agent_ids=[owner_id])
    assert len(page.items) == 1 and page.items[0].id == topic_id
    assert [(item.id, item.display_name, item.user_id) for item in page.items[0].users] == expected
    assert (await topics.list_page(skip=0, limit=10, search="Synthetic participant", agent_ids=[peer_id])).items[0].users == []
    assert (await topics.list_page(skip=500, limit=500, search="Synthetic participant")).items == []
    assert report["bytes"] == 0 and report["rows"] == 0, report


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["list", "detail"])
async def test_skill_file_catalogues_keep_live_access_without_loading_assignment_matrices(db, read_actors, tmp_path, monkeypatch, view):
    owner, peer = read_actors
    owner_id, peer_id = owner.id, peer.id
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    monkeypatch.setattr(storage, "SYSTEM_SKILLS", ())
    category = SkillCategory(label="Synthetic resource category")
    tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == "skills"))
    if tool_id is None:
        tool = ToolModel(code="skills", label="Synthetic Skills")
        db.add(tool)
        await db.flush()
        tool_id = tool.id
    connection = Connection(agent_id=owner.id, tool_id=tool_id, active=True)
    db.add_all([category, connection])
    await db.flush()
    db.add(ConnectionParam(connection_id=connection.id, param_name='tools.management_scope', param_value='all'))
    skills = [Skill(code=f"synthetic-resource-{index:02d}", label=f"Synthetic resource {index:02d}", category_id=category.id) for index in range(41)]
    db.add_all(skills)
    await db.flush()
    db.add_all([AgentSkill(agent_id=agent.id, skill_id=skill.id, active=True) for agent in (owner, peer) for skill in skills])
    db.add_all([AgentSkillCategory(agent_id=agent.id, category_id=category.id, active=True) for agent in (owner, peer)])
    directory = tmp_path / "skills" / skills[0].code
    directory.mkdir(parents=True)
    (directory / "SKILL.md").write_text("---\nname: synthetic-resource-00\ndescription: Synthetic catalogue\n---\n\nComplete synthetic instructions\n")
    code, connection_id = skills[0].code, connection.id
    await db.commit()
    async with measured(db, f"selectors-skill-{view}", {AgentSkill: (), AgentSkillCategory: ()}) as report:
        result = await resource_facade.list_skill_resources(actor_agent_id=owner_id) if view == "list" else await resource_facade.get_skill_resource(code, actor_agent_id=owner_id)
    summary = next(item for item in result if item["code"] == code) if view == "list" else result
    assert summary["available"] and summary["valid"] and summary["file_count"] == 1
    assert summary["description"] == "Synthetic catalogue"
    assert len(await resource_facade.list_skill_resources(actor_agent_id=owner_id, query="  SYNTHETIC CATALOGUE  ")) == 1
    assert await resource_facade.list_skill_resources(actor_agent_id=owner_id, offset=500, limit=500) == []
    assert (await resource_facade.read_skill_file(code, "SKILL.md", actor_agent_id=owner_id)).content.endswith(b"Complete synthetic instructions\n")
    # Ordinary authorized usage is independent of management delegation.
    assert [item['code'] for item in await resource_facade.list_skill_resources(actor_agent_id=peer_id)] == [code]
    db.expunge_all()
    full = await skill_service.get_by_code(code)
    assert full.category and len(full.category.authorizations) == 2
    connection = await db.get(Connection, connection_id)
    connection.active = False
    await db.commit()
    assert await resource_facade.get_skill_resource(code, actor_agent_id=owner_id)
    with pytest.raises(PermissionError):
        await resource_facade.write_skill_file(code, 'SKILL.md', b'Forbidden', actor_agent_id=owner_id)
    # Four extra bounded queries verify the caller and the live server policy;
    # the count remains independent of package/agent count and no matrix loads.
    assert report["queries"] <= 6 and report["rows"] == 0, report
