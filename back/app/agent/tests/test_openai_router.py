"""Agent API failures remain readable by OpenAI-compatible clients."""

import pytest

from app.agent import openai_router
from app.agent.models import Agent
from core.authorize.tests.test_domain_authorization import owned_agent
from core.authorize.tests.test_guard_policy_parameters import actor
from core.database import get_db_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,status,error_type",
    [(RuntimeError("Synthetic agent unavailable"), 502, "agent_error"),
     (ValueError("Synthetic execution failure"), 500, "internal_error")],
)
async def test_agent_completion_errors_use_openai_envelope(client, monkeypatch, error, status, error_type):
    headers, user_id = await actor(["AGENT_API_ACCESS"])
    agent_id = await owned_agent(user_id)
    async with get_db_session() as db:
        agent = await db.get(Agent, agent_id)
        code = agent.code

    async def fail_completion(*args, **kwargs):
        raise error

    monkeypatch.setattr(openai_router, "run_local_chat_completion", fail_completion)
    response = await client.post(
        "/api/agent/openai/chat/completions",
        headers=headers,
        json={"model": code, "messages": [{"role": "user", "content": "Synthetic request"}]},
    )

    assert response.status_code == status
    assert response.json()["error"]["type"] == error_type
    assert str(error) in response.json()["error"]["message"]


@pytest.mark.asyncio
async def test_agent_completion_keeps_authentication_and_privilege_checks(client, monkeypatch):
    async def unexpected_completion(*args, **kwargs):
        pytest.fail("An unauthorized request reached agent execution")

    monkeypatch.setattr(openai_router, "run_local_chat_completion", unexpected_completion)
    payload = {"model": "synthetic-agent", "messages": [{"role": "user", "content": "Hello"}]}
    assert (await client.post("/api/agent/openai/chat/completions", json=payload)).status_code == 401
    headers, _ = await actor([])
    assert (await client.post("/api/agent/openai/chat/completions", headers=headers, json=payload)).status_code == 403
