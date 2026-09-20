"""Public cross-domain background Task submission contract."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.agent import AgentTaskDraft, submit_background_task
from app.agent.task_port import task_port


@pytest.mark.asyncio
async def test_submit_background_task_uses_registered_port(monkeypatch) -> None:
    task_id = uuid4()
    scheduled = []

    async def create(draft):
        assert draft.agent_id == 7
        return SimpleNamespace(id=task_id)

    monkeypatch.setattr(task_port, "create", create)
    monkeypatch.setattr(task_port, "schedule", lambda value: scheduled.append(value))

    result = await submit_background_task(
        AgentTaskDraft(label="Calendar", objective="Review", ai=True, agent_id=7)
    )

    assert result == task_id
    assert scheduled == [task_id]
