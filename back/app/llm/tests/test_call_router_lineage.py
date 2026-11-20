from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.llm import call_router
from app.llm.runtime_correlation import RuntimeLLMTask, resolve_runtime_task_id


@pytest.mark.asyncio
@pytest.mark.parametrize(("runtime_agent", "opt_in", "use_provider_budget"), [
    (True, True, True),
    (True, False, False),
    (False, True, False),
])
async def test_chat_budget_opt_in_requires_an_authenticated_runtime(
    db, monkeypatch: pytest.MonkeyPatch, runtime_agent: bool, opt_in: bool, use_provider_budget: bool,
) -> None:
    monkeypatch.setattr(call_router, "_llm_api_auth", AsyncMock(return_value=42 if runtime_agent else None))
    monkeypatch.setattr(call_router, "resolve_runtime_llm_task", AsyncMock(
        return_value=RuntimeLLMTask(uuid4(), uuid4(), uuid4()) if runtime_agent else None,
    ))

    async def echo(body, **_options):
        return body

    monkeypatch.setattr(call_router, "proxy_chat_completion", echo)
    api = FastAPI()
    api.include_router(call_router.llm_api_router)
    headers = {"X-Galaris-Output-Budget": "provider"} if opt_in else {}
    budget = {"max_tokens": 123, "max_completion_tokens": 456, "max_output_tokens": 789}
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as client:
        response = await client.post("/llm/openai/chat/completions", headers=headers, json={
            "model": "synthetic", **budget,
        })
    assert response.status_code == 200, response.text
    assert response.json() == ({"model": "synthetic"} if use_provider_budget else {"model": "synthetic", **budget})


@pytest.mark.asyncio
async def test_explicit_task_id_wins_without_using_a_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    explicit_task_id = uuid4()
    import app.agent as agent_domain

    monkeypatch.setattr(
        agent_domain,
        "get_current_task",
        lambda _agent_id: pytest.fail("fallback must not be used"),
    )

    assert await resolve_runtime_task_id(
        raw_task_id=str(explicit_task_id),
        messages=[],
        agent_id=42,
    ) == explicit_task_id


@pytest.mark.asyncio
async def test_prompt_task_id_wins_over_the_agent_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompt_task_id = uuid4()
    import app.agent as agent_domain

    monkeypatch.setattr(agent_domain, "get_current_task", lambda _agent_id: uuid4())

    assert await resolve_runtime_task_id(
        raw_task_id=None,
        messages=[
            {
                "role": "user",
                "content": (
                    "<galaris_message_context>\n"
                    f'{{"task_id": "{prompt_task_id}"}}\n'
                    "</galaris_message_context>"
                ),
            }
        ],
        agent_id=42,
    ) == prompt_task_id


@pytest.mark.asyncio
async def test_current_process_task_wins_over_the_durable_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current_task_id = uuid4()
    import app.agent as agent_domain
    import app.task as task_domain

    monkeypatch.setattr(
        agent_domain,
        "get_current_task",
        lambda _agent_id: current_task_id,
    )
    durable_lookup = AsyncMock(return_value=uuid4())
    monkeypatch.setattr(task_domain, "unique_leased_task_for_agent", durable_lookup)

    assert await resolve_runtime_task_id(
        raw_task_id=None,
        messages=[],
        agent_id=42,
    ) == current_task_id
    durable_lookup.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_context", [False, True])
async def test_child_task_snapshot_cannot_replace_the_runtime_task(
    monkeypatch: pytest.MonkeyPatch, with_context: bool,
) -> None:
    import json
    import app.agent as agent_domain
    import app.task as task_domain

    parent_id, child_id = uuid4(), uuid4()
    monkeypatch.setattr(agent_domain, "get_current_task", lambda _agent_id: None)
    durable_lookup = AsyncMock(return_value=parent_id)
    monkeypatch.setattr(task_domain, "unique_leased_task_for_agent", durable_lookup)
    messages = ([{"role": "user", "content": json.dumps({"task_id": str(parent_id)})}]
                if with_context else [])
    messages.append({"role": "tool", "content": json.dumps({
        "id": str(child_id), "agent_id": 43,
        "activity": {"task_id": str(child_id)},
    })})

    assert await resolve_runtime_task_id(
        raw_task_id=None, messages=messages, agent_id=42,
    ) == parent_id
    if with_context:
        durable_lookup.assert_not_awaited()
    else:
        durable_lookup.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_runtime_task_falls_back_to_the_unique_durable_agent_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leased_task_id = uuid4()
    import app.agent as agent_domain
    import app.task as task_domain

    monkeypatch.setattr(agent_domain, "get_current_task", lambda _agent_id: None)
    durable_lookup = AsyncMock(return_value=leased_task_id)
    monkeypatch.setattr(task_domain, "unique_leased_task_for_agent", durable_lookup)

    assert await resolve_runtime_task_id(
        raw_task_id=None,
        messages=[],
        agent_id=42,
    ) == leased_task_id
    durable_lookup.assert_awaited_once_with(42)


@pytest.mark.asyncio
async def test_task_id_stays_empty_without_a_managed_runtime_agent() -> None:
    assert await resolve_runtime_task_id(
        raw_task_id=None,
        messages=[],
        agent_id=None,
    ) is None
