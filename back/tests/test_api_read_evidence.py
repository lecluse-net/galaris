"""Synthetic query and payload budgets for model selectors and evidence views."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.agent import Agent
from app.agent import openai_service
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.conversation import monitoring_service as conversations
from app.lab import comparison_service, dispatcher_evaluation_service, mechanism_evaluation_service
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign
from app.llm import llm_provider_service, model_usages, profile_service
from app.llm.profile_models import LlmProfile, PROFILE_MODEL_FIELDS
from app.llm.provider_models import LLM, LLMProvider
from app.messenger import Message, Room
from app.task import Task, TaskStatus
from app.tools import ToolModel
from app.topic import service as topics
from app.topic.models import Topic
from app.voice.models import VoiceConversationSession
from core.user import UserModel
from tests.test_api_read_lot import measured, read_actors as read_actors


@pytest.mark.asyncio
async def test_agent_models_select_only_codes_and_keep_explicit_dialogue_scope(db, read_actors):
    identifiers = [agent.id for agent in read_actors]
    deleted = Agent(title_id=read_actors[0].title_id, code="synthetic-evidence-deleted", first_name="Deleted", last_name="Synthetic")
    db.add(deleted)
    await db.flush()
    deleted.soft_delete()
    await db.commit()
    identifiers.append(deleted.id)
    async with measured(db, "evidence-models", {Agent: ("avatar", "personality")}) as report:
        result = await openai_service.list_agent_models(agent_ids=identifiers[:1])
    assert [item.id for item in result.data] == ["synthetic-api-read-0"]
    assert (await openai_service.list_agent_models(agent_ids=[])).data == []
    assert "synthetic-evidence-deleted" not in [item.id for item in (await openai_service.list_agent_models(agent_ids=identifiers)).data]
    assert (await db.scalar(select(Agent).where(Agent.id == identifiers[0]))).avatar
    assert report["rows"] == report["bytes"] == 0 and report["queries"] == 1, report


@pytest.mark.asyncio
async def test_provider_owner_options_keep_active_names_without_authentication_data(db):
    db.add_all([UserModel(email=f"synthetic-evidence-{index}@example.com", display_name=f"Owner {index:02d}" if index else "",
                          hashed_password="synthetic-hash", totp_secret_encrypted="x" * 1000,
                          recovery_code_hashes=["synthetic-recovery"] * 30, is_active=index != 3) for index in range(41)])
    await db.commit()
    async with measured(db, "evidence-provider-owners", {UserModel: ("hashed_password", "totp_secret_encrypted", "recovery_code_hashes")}) as report:
        result = await llm_provider_service.get_provider_catalog()
    assert result.active_user_count == len(result.users)
    labels = [item.label for item in result.users]
    assert "synthetic-evidence-0@example.com" in labels and "Owner 03" not in labels
    assert "Owner 40" in labels
    assert report["bytes"] == report["rows"] == 0, report


@pytest.mark.asyncio
async def test_profile_validation_batches_models_without_changing_error_priority(db):
    provider = LLMProvider(name="Synthetic profile evidence", base_url="https://models.example.com", configuration={"large": "x" * 50000})
    db.add(provider)
    await db.flush()
    model = LLM(llm_provider_id=provider.id, code="synthetic-profile-evidence", llm_name="synthetic", label="Synthetic",
                service_capabilities=["chat", "decision", "sound_generation", "music_generation", "video_generation"], pricing={"large": "x" * 50000})
    db.add(model)
    profile = LlmProfile(label="Synthetic evidence", code="synthetic-evidence")
    db.add(profile)
    await db.commit()
    identifier, model_id = profile.id, model.id
    values = {field: str(model_id) for field in PROFILE_MODEL_FIELDS if field != model_usages.VECTOR}
    async with measured(db, "evidence-profile", {LLM: ("pricing",), LLMProvider: ("configuration",)}) as report:
        result = await profile_service.update_profile(identifier, values=values)
    assert all(getattr(result, field) == model_id for field in values)
    for invalid in ({model_usages.TEXT_LOW: "999999999", "unknown": "1"}, {model_usages.TEXT_LOW: "invalid", "unknown": "1"}):
        with pytest.raises(ValueError) as error:
            await profile_service.update_profile(identifier, values=invalid)
        assert "text_low_llm_id" in str(error.value) and "unknown" not in str(error.value)
    with pytest.raises(ValueError):
        await profile_service.update_profile(identifier, values={"decision_fallback_policy": "invalid"})
    assert (await profile_service.get_profile(identifier)).text_low_llm_id == model_id
    assert report["bytes"] == 0 and report["queries"] == 3, report


@pytest.mark.asyncio
async def test_profile_reports_the_first_invalid_field_even_with_oversized_later_ids(db):
    async with measured(db, "evidence-profile-invalid", {}) as report:
        with pytest.raises(ValueError, match="unknown"):
            await profile_service._validate_profile_values({"unknown": "1", model_usages.TEXT_LOW: str(2**80)})
    assert report["queries"] == 0
    with pytest.raises(ValueError, match="text_low_llm_id"):
        await profile_service._validate_profile_values({model_usages.TEXT_LOW: str(2**80)})


@pytest.mark.asyncio
@pytest.mark.parametrize("mechanism", ["dispatcher", "planner"])
async def test_lab_run_detail_omits_frozen_corpus_but_workers_still_read_it(db, mechanism):
    dataset = LabEvaluationDataset(name="Synthetic detail evidence", mechanism=mechanism)
    db.add(dataset)
    await db.flush()
    snapshots = [{"name": "Synthetic case", "input_data": {"large": "x" * 100000}}]
    run = LabEvaluationRun(dataset_id=dataset.id, status="completed", case_snapshots=snapshots, analysis_markdown="Synthetic analysis")
    db.add(run)
    await db.flush()
    identifier = run.id
    db.add(LabEvaluationRunCase(run_id=identifier, case_snapshot={"name": "Synthetic result"}, actual_output={"answer": "Synthetic answer"}))
    await db.commit()
    async with measured(db, f"evidence-run-{mechanism}", {LabEvaluationRun: ("case_snapshots",)}) as report:
        result = await dispatcher_evaluation_service.get_run(identifier) if mechanism == "dispatcher" else await mechanism_evaluation_service.get_run(mechanism, identifier)
    assert result.analysis_markdown == "Synthetic analysis"
    assert result.results[0].actual_output == {"answer": "Synthetic answer"}
    if mechanism == "planner":
        assert (await mechanism_evaluation_service._run(mechanism, identifier)).case_snapshots == snapshots
        assert await mechanism_evaluation_service.get_run("topic", identifier) is None
    else:
        assert (await db.scalar(select(LabEvaluationRun).where(LabEvaluationRun.id == identifier))).case_snapshots == snapshots
    db.expunge_all()
    held = await db.get(LabEvaluationRun, identifier)
    if mechanism == "planner":
        await mechanism_evaluation_service.get_run(mechanism, identifier)
        assert await mechanism_evaluation_service._run(mechanism, identifier) is held
    else:
        await dispatcher_evaluation_service.get_run(identifier)
    assert held.case_snapshots == snapshots
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
async def test_comparison_batches_headers_preserving_latest_judge_and_same_run(db):
    dataset = LabEvaluationDataset(name="Synthetic comparison evidence", mechanism="planner")
    db.add(dataset)
    await db.flush()
    runs = [LabEvaluationRun(dataset_id=dataset.id, status="completed", case_snapshots=[{"large": "x" * 100000}],
                             configuration_snapshot={"fingerprints": {"corpus": "same", "candidate": "same"}}) for _ in range(2)]
    db.add_all(runs)
    await db.flush()
    ids = [run.id for run in runs]
    for run in runs:
        db.add_all([LabJudgmentCampaign(run_id=run.id, sequence=1, configuration={"old": str(run.id)}),
                    LabJudgmentCampaign(run_id=run.id, sequence=2, configuration={})])
        db.add(LabEvaluationRunCase(run_id=run.id, case_snapshot={"name": "Synthetic pair", "input_data": {}, "expected_output": {}}, actual_output={"answer": "kept"}))
    await db.commit()
    async with measured(db, "evidence-comparison", {LabEvaluationRun: ("case_snapshots",)}) as report:
        result = await comparison_service.compare("planner", *ids, "model", include_outputs=True)
    assert result["comparable"] and len(result["items"]) == 1
    assert (await comparison_service.compare("planner", ids[0], ids[0], "model"))["comparable"]
    with pytest.raises(LookupError):
        await comparison_service.compare("planner", ids[0], uuid4(), "model")
    with pytest.raises(LookupError):
        await comparison_service.compare("topic", *ids, "model")
    assert report["bytes"] == 0 and report["queries"] <= 14, report


@pytest_asyncio.fixture
async def evidence_content(db, read_actors):
    owner, peer = read_actors
    tool = ToolModel(code="synthetic-evidence", label="Synthetic evidence")
    topic = Topic(title="Synthetic evidence dossier")
    db.add_all([tool, topic])
    await db.flush()
    connections = [Connection(agent_id=agent.id, tool_id=tool.id) for agent in (owner, peer)]
    db.add_all(connections)
    await db.flush()
    rooms = [Room(connection_id=connection.id, external_id=f"synthetic-evidence-{index}", label=f"Synthetic room {index}", conversation_type="text") for index, connection in enumerate(connections)]
    db.add_all(rooms)
    await db.flush()
    session = VoiceConversationSession(messenger_room_id=rooms[0].id, started_at=datetime.now(timezone.utc), status="COMPLETED")
    db.add(session)
    await db.flush()
    now = datetime.now(timezone.utc)
    rounds, messages, tasks = [], [], []
    for index in range(21):
        timestamp = now - timedelta(seconds=index)
        round_ = ConversationRound(room_id=rooms[0 if index < 20 else 1].id, topic_id=topic.id, status="COMPLETED",
                                    voice_session_id=session.id if index % 2 else None, sequence=index + 1,
                                    effective_objective=f"Synthetic request {index}", created_at=timestamp,
                                    execution_result={"large": "r" * 50000}, encrypted_checkpoint="c" * 50000,
                                    process_launch_admission={"large": "p" * 50000})
        message = Message(connection_id=connections[0 if index < 20 else 1].id, messenger_room_id=round_.room_id,
                          platform="synthetic", remote_message_id=f"synthetic-{index}", direction="inbound", topic_id=topic.id,
                          text=f"Synthetic message {index}", created_at=timestamp,
                          metadata_={"sender_id": "synthetic-sender", "sender_display_name": "Synthetic sender", "large": "m" * 50000},
                          attachments=[{"uri": "https://files.example.com/synthetic", "label": "a" * 50000}])
        task = Task(agent_id=owner.id if index < 20 else peer.id, topic_id=topic.id, label=f"Synthetic task {index}",
                    objective=f"Synthetic objective {index}", status=TaskStatus.SUCCESS, created_at=timestamp,
                    data={"large": "t" * 50000})
        db.add_all([round_, message, task])
        await db.flush()
        db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
        rounds.append(round_.id)
        messages.append(message.id)
        tasks.append(task.id)
    await db.commit()
    return {"topic": topic.id, "owner": owner.id, "peer": peer.id, "rounds": rounds, "messages": messages, "tasks": tasks}


@pytest.mark.asyncio
async def test_message_monitoring_keeps_senders_pagination_scope_without_media_payload(db, evidence_content):
    async with measured(db, "evidence-messages", {Message: ("attachments", "metadata_")}) as report:
        result = await conversations.list_messages(page=1, page_size=10, agent_ids=[evidence_content["owner"]])
    assert result.total == 20 and len(result.items) == 10
    assert result.items[0].payload["sender"]["id"] == "synthetic-sender"
    assert result.items[0].payload["sender"]["display_name"] == "Synthetic sender"
    assert [item.id for item in result.items] == evidence_content["messages"][:10]
    assert (await conversations.list_messages(page=2, page_size=10, agent_ids=[evidence_content["owner"]])).items[0].id == evidence_content["messages"][10]
    assert (await conversations.list_messages(page=1, page_size=500, agent_ids=[])).total == 0
    assert report["bytes"] == 0 and report["queries"] == 3, report


@pytest.mark.asyncio
async def test_round_detail_keeps_execution_evidence_without_runtime_checkpoint(db, evidence_content):
    identifier = evidence_content["rounds"][0]
    async with measured(db, "evidence-round", {ConversationRound: ("encrypted_checkpoint", "process_launch_admission")}) as report:
        result = await conversations.get_round(identifier)
    assert result.execution_result == {"large": "r" * 50000}
    assert result.rendered_input[0]["text"] == "Synthetic message 0"
    full = await db.scalar(select(ConversationRound).where(ConversationRound.id == identifier))
    assert full.encrypted_checkpoint == "c" * 50000 and full.process_launch_admission == {"large": "p" * 50000}
    db.expunge_all()
    held = await db.get(ConversationRound, identifier)
    await conversations.get_round(identifier)
    assert held.encrypted_checkpoint == "c" * 50000
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["content", "task", "message", "conversation_round", "voice_turn"])
async def test_topic_recaps_and_mcp_items_keep_counts_order_and_full_storage(db, evidence_content, view):
    topic_id = evidence_content["topic"]
    async with measured(db, f"evidence-topic-{view}", {Task: ("data",), Message: ("attachments", "metadata_"),
                                                      ConversationRound: ("execution_result", "encrypted_checkpoint", "process_launch_admission")}) as report:
        if view == "content":
            result = await topics.get_content(topic_id, limit=10, agent_ids=[evidence_content["owner"]])
        else:
            result = await topics.list_items(topic_id, item_type=view, offset=1, limit=10)
    if view == "content":
        assert result.summary.tasks == 20 and result.summary.conversation_rounds == result.summary.voice_turns == 10
        assert [item.id for item in result.tasks] == evidence_content["tasks"][:10]
        assert result.conversation_rounds[0].preview == "Synthetic request 0"
        assert result.voice_turns[0].preview == "Synthetic request 1"
        empty = await topics.get_content(topic_id, agent_ids=[])
        assert empty.summary.tasks == empty.summary.rooms == empty.summary.conversation_rounds == empty.summary.voice_turns == 0
    else:
        assert len(result.items) == (9 if view == "voice_turn" else 10)
        assert result.offset == 1
        assert (await topics.list_items(topic_id, item_type=view, offset=500, limit=500)).items == []
    assert (await db.scalar(select(Task).where(Task.id == evidence_content["tasks"][0]))).data == {"large": "t" * 50000}
    assert report["bytes"] == 0, report
