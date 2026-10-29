"""The optimized API projections retain authentication, scope and reopen behavior."""

import pytest
from uuid import uuid4
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.incident.models import FailureIncident, FailurePattern
from app.lab.models import LabTask
from app.lab.process_evaluation_models import LabProcessCampaign, LabProcessCase
from app.llm.provider_models import LLM, LLMProvider
from app.dataset.facade import create_dataset
from app.memory.tests.conftest import memory_storage as memory_storage
from app.process.bpmn import to_bpmn
from app.process.models import ProcessDefinition, ProcessDefinitionRevision
from app.process.tests.test_native_bpmn import graph
from app.skill.models import Skill, AgentSkill
from app.skill import storage
from app.task import Task
from app.tools.models import Tool
from core.authorize.models import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.user_service import encrypt_password


@pytest.mark.asyncio
async def test_read_lot_http_rights_scope_and_reopening(client, memory_storage, tmp_path, monkeypatch):
    from datetime import datetime, timezone

    password = "synthetic-read-lot-password"
    monkeypatch.setattr(type(storage.settings), "GALARIS_SKILLS_ROOT", str(tmp_path / "skills"))
    async with get_db_session() as db:
        codes = ["SKILL_ACCESS", "LLM_API_ACCESS", "EVALUATION_ACCESS", "PROCESS_EVALUATION_ACCESS",
                 "PROCESS_READ", "INCIDENT_ACCESS", "MEMORY_ACCESS"]
        privileges = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        assert len(privileges) == len(codes)
        role = Role(code="synthetic-read-lot", privileges=privileges)
        hashed_password = encrypt_password(password)
        users = [UserModel(email=f"api-read-lot-{index}@example.com", is_active=True, hashed_password=hashed_password)
                 for index in range(3)]
        title = Title(label="Synthetic HTTP lot", gender="N")
        db.add_all([role, title, *users])
        await db.flush()
        db.add_all([Assignment(user_id=user.id, role_id=role.id, is_default=True) for user in users[:2]])
        agents = [Agent(user_id=user.id, title_id=title.id, code=f"synthetic-http-lot-{index}",
                        first_name="Synthetic", last_name=str(index)) for index, user in enumerate(users[:2])]
        db.add_all(agents)
        await db.flush()
        owner_id = agents[0].id
        db.add(Skill(code="synthetic-http-catalogue", label="Synthetic HTTP catalogue"))
        learned = [Skill(owner_agent_id=agent.id, code=f"synthetic-http-learned-{index}", label="Synthetic procedure",
                         learning_key=uuid4())
                   for index, agent in enumerate(agents)]
        tasks = [Task(agent_id=agent.id, label=f"Synthetic HTTP Task {index}", data={"synthetic": "private payload"})
                 for index, agent in enumerate(agents)]
        selected = Task(agent_id=owner_id, label="Synthetic HTTP selected Task")
        provider = LLMProvider(name="Synthetic HTTP models", base_url="https://models.example.com")
        db.add_all([*learned, *tasks, selected, provider])
        await db.flush()
        for package in learned:
            db.add(AgentSkill(skill_id=package.id, agent_id=package.owner_agent_id, active=True))
            await storage.install_markdown(package.code, package.label,
                f"---\nname: {package.code}\ndescription: Synthetic description\n---\nSynthetic complete procedure\n",
                owner_agent_id=package.owner_agent_id)
        db.add(LabTask(task_id=selected.id))
        db.add_all([LLM(llm_provider_id=provider.id, code=f"synthetic-http-{capability}", llm_name=f"synthetic/{capability}",
                        label=f"Synthetic {capability}", service_capabilities=[capability]) for capability in ("chat", "speech")])
        tool_id = await db.scalar(select(Tool.id).where(Tool.code == "galaris"))
        process = ProcessDefinition(agent_id=owner_id, tool_id=tool_id, engine_process_id="synthetic_http_read",
                                    code="synthetic_http_read", label="Synthetic Process",
                                    bpmn_xml=to_bpmn(graph(), "synthetic_http_read"))
        db.add(process)
        await db.flush()
        db.add(ProcessDefinitionRevision(process_id=process.id, revision=1, bpmn_xml=process.bpmn_xml,
                                          author_agent_id=owner_id))
        dataset = await create_dataset(owner_id, title="Synthetic HTTP campaign source",
                                       content='{"synthetic":true,"cases":[{"input":{}}]}')
        campaign = LabProcessCampaign(owner_agent_id=owner_id, owner_user_id=users[0].id,
                                       dataset_id=dataset.id, process_code=process.code,
                                       title="Synthetic campaign", invocation_key="synthetic-http", fingerprint="s" * 64)
        db.add(campaign)
        await db.flush()
        db.add(LabProcessCase(campaign_id=campaign.id, position=0, input={"synthetic": True}, evidence={"synthetic": True}))
        now = datetime.now(timezone.utc)
        pattern = FailurePattern(fingerprint="synthetic-http-lot", kind="tool", category="synthetic",
                                  title="Synthetic pattern", first_seen_at=now, last_seen_at=now,
                                  diagnosis="Synthetic detailed diagnosis")
        db.add(pattern)
        await db.flush()
        db.add(FailureIncident(pattern_id=pattern.id, idempotency_key="synthetic-http-lot", kind="tool", category="synthetic",
                                phase="execute", severity="error", error_type="SyntheticError", error_message="Synthetic failure",
                                occurred_at=now))
        await db.flush()
        own_task_id, selected_id = str(tasks[0].id), str(selected.id)
        learned_id, campaign_id = learned[0].id, str(campaign.id)

    process_path = "/api/processes/internal/definitions/synthetic_http_read/history"
    campaign_path = f"/api/evaluation/process-campaigns/{campaign_id}"
    paths = ["/api/skills", "/api/skills/personal", "/api/incidents", "/api/evaluation/candidates",
             "/api/evaluation/tasks", "/api/evaluation/config", "/api/llm/openai/models",
             "/api/llm/anthropic/v1/models", process_path, campaign_path]
    for path in paths:
        assert (await client.get(path)).status_code == 401, path
    headers = []
    for index in range(3):
        login = await client.post("/api/auth/login-json", json={
            "email": f"api-read-lot-{index}@example.com", "password": password,
        })
        assert login.status_code == 200, login.text
        headers.append({"Authorization": f"Bearer {login.json()['access_token']}"})
    responses = {}
    for path in paths:
        assert (await client.get(path, headers=headers[2])).status_code == 403, path
        result = await client.get(path, headers=headers[0])
        assert result.status_code == 200, (path, result.text)
        responses[path] = result.json()
        assert (await client.get(path, headers=headers[0])).json() == result.json(), path
    assert any(item["code"] == "synthetic-http-catalogue" for item in responses["/api/skills"])
    assert [item["id"] for item in responses["/api/skills/personal"]["items"]] == [learned_id]
    assert "markdown" not in responses["/api/skills/personal"]["items"][0]
    detail = await client.get(f"/api/skills/personal/{learned_id}", headers=headers[0])
    assert detail.status_code == 200 and detail.json()["skill"]["learning"] is not None
    assert (await client.get(f"/api/skills/personal/{learned_id}", headers=headers[1])).status_code == 404
    assert [item["task_id"] for item in responses["/api/evaluation/candidates"]] == [own_task_id]
    assert responses["/api/evaluation/tasks"][0]["task_id"] == selected_id
    for path in ("/api/llm/openai/models", "/api/llm/anthropic/v1/models"):
        model_codes = {item["id"] for item in responses[path]["data"]}
        assert "synthetic-http-chat" in model_codes and "synthetic-http-speech" not in model_codes
    assert responses[process_path]["items"][0]["revision"] == 1
    assert responses[campaign_path]["items"][0]["evidence"] == {"synthetic": True}
    assert (await client.get(process_path, headers=headers[1])).status_code == 403
    assert (await client.get(campaign_path, headers=headers[1])).status_code == 403
