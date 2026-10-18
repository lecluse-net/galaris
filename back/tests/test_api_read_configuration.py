"""Synthetic SQL budgets for configuration and supervision API consumers."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select, update

from app.agent import Agent
from app.connection import Connection, connection_service
from app.connection.models import ConnectionParam
from app.conversation import ConversationRound
from app.goal import goal_service
from app.goal.models import Goal, GoalReferrerType
from app.goal.tests.factories import make_goal
from app.llm import personal_service
from app.llm import model_metadata_service
from app.llm.handlers import LLMModelInfo, OpenAICompatibleHandler
from app.llm.provider_models import LLM, LLMProvider
from app.memory.tests.conftest import memory_storage as memory_storage
from app.onboarding import services as onboarding
from app.tools import ToolModel
from app.voice import monitoring_service as voice
from app.voice.models import VoiceConversationSession
from app.messenger import Room
from core.user import UserModel
from core.user import user_service
from core.user.schemas import User as PublicUser
from core.util import SECRET_MASK, get_encryption_service
from tests.test_api_read_lot import measured, read_actors as read_actors


@pytest.mark.asyncio
@pytest.mark.parametrize("size", [1, 41, 501])
async def test_connection_batch_bounds_reads_and_preserves_encryption_and_validation(db, read_actors, size):
    owner = read_actors[0]
    definitions = {f"value{index}": {"type": "string"} for index in range(size)}
    definitions.update(token={"type": "password"}, count={"type": "integer"}, fixed={"type": "string"})
    tool = ToolModel(code=f"synthetic-batch-{size}", label="Synthetic parameter batch",
                     connection_schema={"params": definitions}, global_params={"fixed": {"value": "global", "forced": True}})
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=owner.id, active=True)
    db.add(connection)
    await db.flush()
    identifier = connection.id
    await connection_service.set_param(identifier, "token", "synthetic-batch-secret")
    params = {f"value{index}": f"Synthetic value {index}" for index in range(size)}
    params.update(token=SECRET_MASK, count="7")
    async with measured(db, f"configuration-bulk-{size}", {}) as report:
        saved = await connection_service.set_params_bulk(identifier, params)
    assert [row.param_name for row in saved] == list(params)
    assert len({row.id for row in saved}) == size + 2
    assert get_encryption_service().is_encrypted(next(row.param_value for row in saved if row.param_name == "token"))
    assert await connection_service.get_param(identifier, "token") == "synthetic-batch-secret"
    for invalid in ({"value0": "must not persist", "count": "invalid"}, {"fixed": "local"}, {"unknown": "value"}):
        with pytest.raises(ValueError):
            await connection_service.set_params_bulk(identifier, invalid)
    assert await connection_service.get_param(identifier, "value0") == "Synthetic value 0"
    await connection_service.set_params_bulk(identifier, {"token": "synthetic-rotated-secret", "count": "9"})
    assert await connection_service.get_param(identifier, "token") == "synthetic-rotated-secret"
    assert await connection_service.set_params_bulk(identifier, {}) == []
    with pytest.raises(ValueError):
        await connection_service.set_params_bulk(-1, params)
    await connection_service.set_param(identifier, "token", None)
    with pytest.raises(ValueError, match="existing secret"):
        await connection_service.set_params_bulk(identifier, {"value0": "must not persist", "token": SECRET_MASK})
    assert await connection_service.get_param(identifier, "value0") == "Synthetic value 0"
    assert report["queries"] <= 12, report


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["page", "tree"])
async def test_goal_hierarchies_keep_counts_names_and_scope_without_loading_children(db, read_actors, memory_storage, view):
    owner, referrer = read_actors
    owner_id, referrer_id = owner.id, referrer.id
    owner.personality = "<p>Synthetic personality</p>" * 5000
    referrer.personality = "<p>Synthetic referrer</p>" * 5000
    roots = []
    now = datetime.now(timezone.utc)
    for index in range(5):
        root = await make_goal(agent_id=owner_id, title=f"Synthetic root {index}", description=f"<p>Description {index}</p>",
                               tracking_content=f"<p>Tracking {index}</p>", referrer_type=GoalReferrerType.AGENT,
                               referrer_agent_id=referrer_id, updated_at=now - timedelta(seconds=index))
        db.add(root)
        await db.flush()
        roots.append(root)
        for child_index in range(6):
            child = await make_goal(agent_id=owner_id if child_index < 4 else referrer_id,
                                    title=f"Synthetic child {index}-{child_index}", description="<p>Child</p>",
                                    parent_goal_id=root.id, last_error="Synthetic diagnostic " * 1000)
            if child_index == 5:
                child.soft_delete()
            db.add(child)
    await db.commit()
    root_ids = [root.id for root in roots]
    fields = {Agent: ("avatar", "personality")}
    if view == "tree":
        fields[Goal] = ("last_error",)
    async with measured(db, f"configuration-goals-{view}", fields) as report:
        result = await goal_service.list_page(search="Synthetic root", agent_ids=[owner_id, referrer_id]) if view == "page" else await goal_service.list_tree(agent_ids=[owner_id])
    listed = {item.id: item for item in result.items}
    for index, identity in enumerate(root_ids):
        assert listed[identity].children_count == 5
        assert listed[identity].agent_code == "synthetic-api-read-0"
        assert listed[identity].agent_name.endswith("Synthetic 0")
        if view == "page":
            assert listed[identity].description == f"<p>Description {index}</p>"
            assert listed[identity].referrer.agent_code == "synthetic-api-read-1"
    if view == "page":
        assert [item.id for item in result.items] == root_ids
        assert (await goal_service.list_page(search="Synthetic root", skip=1, limit=2, agent_ids=[owner_id, referrer_id])).items == result.items[1:3]
        assert (await goal_service.list_page(search="Synthetic root", agent_ids=[referrer_id])).items == []
    assert (await goal_service.list_tree(agent_ids=[])).items == []
    db.expunge_all()
    full = await goal_service.get_by_id(root_ids[0])
    assert full and full.agent.personality and len(full.children) == 5
    assert (await goal_service.get_detail(root_ids[0])).children_count == 5
    db.expunge_all()
    held = await db.get(Goal, root_ids[0])
    if view == "tree":
        await goal_service.list_tree(agent_ids=[owner_id])
    else:
        await goal_service.list_page(search="Synthetic root", agent_ids=[owner_id, referrer_id])
    full = await goal_service.get_by_id(root_ids[0])
    assert full is held and full.agent.personality
    assert report["bytes"] == 0, report
    if view == "tree":
        assert report["queries"] == 1, report


@pytest.mark.asyncio
async def test_public_user_list_keeps_sort_search_and_profiles_without_authentication_material(db):
    users = [UserModel(email=f"synthetic-public-{index:02d}@example.com", display_name=f"Public {index:02d}",
                       hashed_password="synthetic-hash", totp_secret_encrypted="synthetic-secret",
                       recovery_code_hashes=[f"synthetic-recovery-{offset}" for offset in range(10)],
                       language="fr", document_open_mode="dialog", is_active=index % 2 == 0) for index in range(41)]
    db.add_all(users)
    await db.commit()
    ids = [user.id for user in users]
    async with measured(db, "configuration-users", {UserModel: ("hashed_password", "totp_secret_encrypted", "recovery_code_hashes")}) as report:
        rows = await user_service.get_users(search="synthetic-public-", sort_by="display_name", descending=True, limit=500, public_only=True)
        result = [PublicUser.model_validate(row) for row in rows]
    assert [user.id for user in result] == list(reversed(ids))
    assert all(user.language == "fr" and user.document_open_mode == "dialog" for user in result)
    assert [row.id for row in await user_service.get_users(search="synthetic-public-", skip=10, limit=10)] == ids[10:20]
    assert (await user_service.get_user_by_id(ids[0])).hashed_password == "synthetic-hash"
    assert report["bytes"] == 0 and report["queries"] == 1, report


@pytest.mark.asyncio
async def test_voice_options_filter_models_and_keep_native_catalog_failure_behavior(db, monkeypatch):
    provider = LLMProvider(name="Synthetic selection", base_url="https://models.example.com", configuration={"unused": "x" * 50000},
                           api_key=get_encryption_service().encrypt("synthetic-upstream-key"),
                           oauth_credentials="synthetic-opaque-token" * 1000)
    inactive = LLMProvider(name="Synthetic inactive", base_url="https://inactive.example.com", is_active=False)
    db.add_all([provider, inactive])
    await db.flush()
    resources = [LLM(llm_provider_id=provider.id, code=f"synthetic-selection-{index}", llm_name=f"model-{index}", label=f"Model {index:02d}",
                     service_capabilities=["chat"] if index < 41 else ["speech"] if index == 41 else ["realtime_conversation"],
                     pricing={"unused": "x" * 30000}) for index in range(44)]
    db.add_all([*resources, LLM(llm_provider_id=inactive.id, code="synthetic-inactive-voice", llm_name="inactive", label="Inactive", service_capabilities=["speech"])])
    await db.commit()
    speech_id, native_ids, provider_id = resources[41].id, [row.id for row in resources[42:]], provider.id
    catalogue = AsyncMock(return_value=[LLMModelInfo(id="voice:synthetic", name="Synthetic Voice", resource_type="voice", service_capabilities=["speech"])])
    monkeypatch.setattr(OpenAICompatibleHandler, "list_models", catalogue)
    monkeypatch.setattr(model_metadata_service, "model_catalog_metadata", lambda: None)
    async with measured(db, "configuration-voice-options", {LLM: ("pricing",)}) as report:
        result = await personal_service.selection_options()
    assert [row.id for row in result.voices if row.id == speech_id] == [speech_id]
    assert [(row.model_id, row.voice_code) for row in result.native_voices] == [(identity, "voice:synthetic") for identity in native_ids]
    catalogue.assert_awaited_once_with("https://models.example.com", "synthetic-upstream-key")
    catalogue.side_effect = RuntimeError("Synthetic catalogue unavailable")
    degraded = await personal_service.selection_options()
    assert degraded.native_voices_error and degraded.native_voices == [] and degraded.voices == result.voices
    assert report["bytes"] == 0, report


@pytest.mark.asyncio
@pytest.mark.parametrize("check", ["llm", "messaging"])
async def test_welcome_checks_do_not_load_full_configuration_payloads(db, read_actors, monkeypatch, check):
    owner_id = read_actors[0].id
    if check == "llm":
        await db.execute(update(LLMProvider).values(is_active=False))
        providers = [LLMProvider(name=f"Synthetic welcome {index}", base_url="http://local-model.example.com:11434",
                                 configuration={"unused": "x" * 30000}) for index in range(41)]
        db.add_all(providers)
        await db.flush()
        db.add_all([LLM(llm_provider_id=row.id, code=f"synthetic-welcome-{index}", llm_name="synthetic", label="Synthetic") for index, row in enumerate(providers)])
        fields = {LLMProvider: ("configuration",)}
    else:
        monkeypatch.setattr(onboarding, "enabled_specs", lambda: [SimpleNamespace(kind="telegram")])
        tools = [ToolModel(code=f"synthetic-welcome-{index}", label="Synthetic messaging", description="x" * 30000,
                           messenger_config={"service": "telegram"}, connection_schema={"unused": "x" * 30000}) for index in range(41)]
        db.add_all(tools)
        await db.flush()
        db.add_all([Connection(agent_id=owner_id, tool_id=row.id, active=True) for row in tools])
        fields = {ToolModel: ("description", "connection_schema")}
    await db.commit()
    async with measured(db, f"configuration-onboarding-{check}", fields) as report:
        result = await onboarding.check_llm_status() if check == "llm" else await onboarding.check_messaging_status(agent_ids=[owner_id])
    assert result is True
    if check == "messaging":
        assert await onboarding.check_messaging_status(agent_ids=[]) is False
    else:
        assert await onboarding.check_agent_status(agent_ids=[owner_id]) is True
        assert await onboarding.check_agent_status(agent_ids=[]) is False
        owner = await db.get(Agent, owner_id)
        owner.soft_delete()
        await db.commit()
        assert await onboarding.check_agent_status(agent_ids=[owner_id]) is False
        assert await onboarding.check_agent_status() is True
    assert report["bytes"] == 0 and report["queries"] == 1, report


@pytest.mark.asyncio
@pytest.mark.parametrize("view", ["list", "detail"])
async def test_voice_monitoring_omits_checkpoints_while_turn_detail_keeps_driver_result(db, read_actors, view):
    owner_id = read_actors[0].id
    tool_id = await db.scalar(select(ToolModel.id).where(ToolModel.code == "galaris"))
    connection = Connection(agent_id=owner_id, tool_id=tool_id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(connection_id=connection.id, external_id="synthetic-voice-monitoring", label="Synthetic Call", conversation_type="audio")
    db.add(room)
    await db.flush()
    now = datetime.now(timezone.utc)
    session = VoiceConversationSession(messenger_room_id=room.id, started_at=now - timedelta(minutes=1), finished_at=now, status="COMPLETED")
    db.add(session)
    await db.flush()
    rounds = [ConversationRound(room_id=room.id, voice_session_id=session.id, sequence=index + 1, status="COMPLETED",
                                 effective_objective=f"Synthetic objective {index}", execution_result={"synthetic": "x" * 30000},
                                 encrypted_checkpoint="synthetic-opaque" * 2000, created_at=now - timedelta(seconds=41 - index)) for index in range(41)]
    db.add_all(rounds)
    await db.commit()
    identity, round_id = session.id, rounds[0].id
    async with measured(db, f"configuration-voice-{view}", {ConversationRound: ("execution_result", "encrypted_checkpoint")}) as report:
        result = await voice.list_conversations(page=1, page_size=50, agent_ids=[owner_id]) if view == "list" else await voice.get_conversation(identity)
    detail = result.items[0] if view == "list" else result
    assert detail.id == identity and detail.turn_count == 41
    assert [turn.effective_objective for turn in detail.turns] == [f"Synthetic objective {index}" for index in range(41)]
    assert (await voice.list_conversations(page=1, page_size=500, agent_ids=[])).total == 0
    db.expunge_all()
    full = await voice.get_turn(round_id)
    assert full is not None and full.execution_result == {"synthetic": "x" * 30000}
    assert report["bytes"] == 0, report
