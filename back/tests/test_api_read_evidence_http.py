"""Exercise evidence projections through authentication, RBAC and real routing."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.agent import Agent
from app.agent.models import Title
from app.connection import Connection
from app.conversation import ConversationRound, ConversationRoundMessage
from app.lab.models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign
from app.llm.profile_models import LlmProfile
from app.llm.provider_models import LLM, LLMProvider
from app.messenger import Message, Room
from app.task import Task, TaskStatus
from app.tools import ToolModel
from app.topic.models import Topic
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_evidence_routes_keep_scope_authorization_outputs_and_reopening(client):
    password = "synthetic-evidence-password"
    async with get_db_session() as db:
        codes = ["AGENT_API_ACCESS", "LLM_PROVIDER_ACCESS", "PARAMS_EDIT", "TASK_ACCESS", "TOPIC_ACCESS",
                 "DISPATCHER_EVALUATION_ACCESS", "PLANNER_EVALUATION_ACCESS"]
        permissions = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        assert len(permissions) == len(codes)
        role = Role(code="synthetic-evidence-reader", privileges=permissions)
        hashed = encrypt_password(password)
        users = [UserModel(email=f"synthetic-evidence-http-{index}@example.com", hashed_password=hashed, is_active=True) for index in range(3)]
        title = Title(label="Synthetic evidence HTTP", gender="N")
        tool = ToolModel(code="synthetic-evidence-http", label="Synthetic evidence")
        topic = Topic(title="Synthetic HTTP evidence")
        provider = LLMProvider(name="Synthetic HTTP model", base_url="https://models.example.com")
        profile = LlmProfile(label="Synthetic HTTP profile", code="synthetic-http-profile")
        db.add_all([role, *users, title, tool, topic, provider, profile])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-evidence-http-{index}", first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users[:2])]
        db.add_all(agents)
        await db.flush()
        connection = Connection(tool_id=tool.id, agent_id=agents[0].id)
        model = LLM(llm_provider_id=provider.id, code="synthetic-http-evidence", llm_name="synthetic", label="Synthetic model")
        db.add_all([connection, model])
        await db.flush()
        room = Room(connection_id=connection.id, external_id="synthetic-http-evidence", label="Synthetic HTTP room", conversation_type="text")
        task = Task(agent_id=agents[0].id, topic_id=topic.id, label="Synthetic HTTP task", objective="Synthetic objective", status=TaskStatus.SUCCESS)
        db.add_all([room, task])
        await db.flush()
        round_ = ConversationRound(room_id=room.id, topic_id=topic.id, status="COMPLETED", execution_result={"answer": "Synthetic result"})
        message = Message(connection_id=connection.id, messenger_room_id=room.id, remote_message_id="synthetic-http-evidence",
                          platform="synthetic", direction="inbound", text="Synthetic HTTP message",
                          metadata_={"sender_id": "synthetic-human", "sender_display_name": "Synthetic human"})
        datasets = [LabEvaluationDataset(name=f"Synthetic HTTP {mechanism}", mechanism=mechanism) for mechanism in ("dispatcher", "planner")]
        db.add_all([round_, message, *datasets])
        await db.flush()
        db.add(ConversationRoundMessage(round_id=round_.id, message_id=message.id, role="input", sequence=1))
        runs = [LabEvaluationRun(dataset_id=dataset.id, status="completed", configuration_snapshot={"fingerprints": {"corpus": "same", "candidate": "same"}},
                                 case_snapshots=[{"synthetic": "Frozen evidence"}]) for dataset in (datasets[0], datasets[1], datasets[1])]
        db.add_all(runs)
        await db.flush()
        for run in runs:
            db.add(LabJudgmentCampaign(run_id=run.id, configuration={"rubric": "synthetic"}))
            db.add(LabEvaluationRunCase(run_id=run.id, case_snapshot={"name": "Synthetic case", "input_data": {"q": "Synthetic question"}, "expected_output": {"answer": "Synthetic reference"}},
                                        actual_output={"answer": "Synthetic output"}))
        run_ids, round_id, topic_id = [str(run.id) for run in runs], str(round_.id), str(topic.id)
        profile_id, model_id, task_id = profile.id, model.id, str(task.id)
    comparison = f"/api/evaluation/planner/runs/compare?left_run_id={run_ids[1]}&right_run_id={run_ids[2]}&limit=500"
    paths = ["/api/agent/openai/models", "/api/llm-providers/catalog", f"/api/evaluation/dispatcher/runs/{run_ids[0]}",
             f"/api/evaluation/planner/runs/{run_ids[1]}", comparison, "/api/conversations/messages?page_size=500",
             f"/api/conversations/rounds/{round_id}", f"/api/topics/{topic_id}/content?limit=500"]
    profile_path = f"/api/llm-profiles/{profile_id}"
    for path in paths:
        assert (await client.get(path)).status_code == 401, path
    assert (await client.put(profile_path, json={"text_low_llm_id": model_id})).status_code == 401
    headers = []
    for index in range(3):
        login = await client.post("/api/auth/login-json", json={"email": f"synthetic-evidence-http-{index}@example.com", "password": password})
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    results = []
    for path in paths:
        assert (await client.get(path, headers=headers[2])).status_code == 403, path
        response = await client.get(path, headers=headers[0])
        assert response.status_code == 200, (path, response.text)
        results.append(response.json())
        assert (await client.get(path, headers=headers[0])).json() == response.json()
    assert [item["id"] for item in results[0]["data"]] == ["synthetic-evidence-http-0"]
    assert [item["id"] for item in (await client.get(paths[0], headers=headers[1])).json()["data"]] == ["synthetic-evidence-http-1"]
    assert results[4]["comparable"] and results[4]["items"][0]["left_output"] == {"answer": "Synthetic output"}
    assert results[5]["items"][0]["payload"]["sender"]["id"] == "synthetic-human"
    assert results[6]["execution_result"] == {"answer": "Synthetic result"}
    assert results[7]["tasks"][0]["id"] == task_id
    assert (await client.get(paths[5], headers=headers[1])).json()["items"] == []
    assert (await client.get(paths[6], headers=headers[1])).status_code == 404
    assert (await client.get(paths[7], headers=headers[1])).json()["tasks"] == []
    assert (await client.put(profile_path, headers=headers[2], json={"text_low_llm_id": model_id})).status_code == 403
    response = await client.put(profile_path, headers=headers[0], json={"text_low_llm_id": model_id})
    assert response.status_code == 200 and response.json()["text_low_llm_id"] == model_id, response.text
    assert (await client.put(profile_path, headers=headers[0], json={"text_low_llm_id": 999999999})).status_code == 400
    assert (await client.get(profile_path, headers=headers[0])).json()["text_low_llm_id"] == model_id
    assert (await client.get(f"/api/conversations/rounds/{uuid4()}", headers=headers[0])).status_code == 404
