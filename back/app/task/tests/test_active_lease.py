from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.agent.models import Agent, Title
from app.task import unique_leased_task_for_agent
from app.task.models import Task, TaskStatus


@pytest.mark.asyncio
async def test_unique_leased_task_lookup_fails_closed_when_ambiguous(db) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Durable runtime lookup {suffix}", gender="X")
    db.add(title)
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Durable",
        last_name="Runtime",
        code=f"durable-runtime-{suffix}",
    )
    db.add(agent)
    await db.flush()
    agent_id = agent.id
    title_id = title.id
    first_id = uuid4()
    second_id = uuid4()
    first = Task(
        id=first_id,
        label="First leased task",
        status=TaskStatus.EXEC,
        agent_id=agent_id,
        lease_token=uuid4(),
        lease_expires_at=datetime.now(timezone.utc).replace(year=2099),
    )
    db.add(first)
    await db.commit()

    assert await unique_leased_task_for_agent(agent_id) == first_id

    db.add(
        Task(
            id=second_id,
            label="Second leased task",
            status=TaskStatus.EXEC,
            agent_id=agent_id,
            lease_token=uuid4(),
            lease_expires_at=datetime.now(timezone.utc).replace(year=2099),
        )
    )
    await db.commit()

    assert await unique_leased_task_for_agent(agent_id) is None

    await db.execute(delete(Task).where(Task.id.in_([first_id, second_id])))
    await db.execute(delete(Agent).where(Agent.id == agent_id))
    await db.execute(delete(Title).where(Title.id == title_id))
    await db.commit()
