from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.llm.runtime_correlation import resolve_runtime_task_id


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
