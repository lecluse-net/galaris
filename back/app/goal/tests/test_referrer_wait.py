from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast
from uuid import UUID, uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.goal import goal_service
from app.goal.models import Goal, GoalReferrerType, GoalStatus
from app.goal.tests.factories import make_goal
from app.goal import referrer_wait
from app.messenger import interactions
from app.messenger.models import (
    Interaction,
    Message,
    Room,
    MessengerUser,
)
from app.task import collab, task_service
from app.task.models import Task, TaskStatus
from app.tools.models import Tool


class _FakeMessenger:
    kind = "test_messenger"
    self_id = "goal-agent"

    def __init__(self, tool_id: int) -> None:
        self.tool_id = tool_id
        self.sent: list[tuple[str, str]] = []

    async def ensure_direct_room(self, user_id: str) -> Room:
        assert user_id == "human-referrer"
        return Room(
            id=UUID("00000000-0000-0000-0000-000000000201"),
            connection_id=0,
            external_id="dm-human-referrer",
            label="Human Referrer",
            kind="direct",
            conversation_type="text",
        )

    async def send_to_room(
        self, room_id: str, text: str, reply_to: str | None = None
    ) -> Message:
        assert reply_to is None
        self.sent.append((room_id, text))
        return Message(
            id=uuid4(),
            connection_id=cast(int, None),
            tool_id=self.tool_id,
            platform=self.kind,
            remote_message_id=f"sent-{len(self.sent)}",
            direction="outbound",
            text=text,
            created_at=datetime.now(timezone.utc),
        )


async def _new_agent(db) -> Agent:
    title_id = await db.scalar(select(Title.id).limit(1))
    if title_id is None:
        title = Title(label="Test", gender="M")
        db.add(title)
        await db.flush()
        title_id = title.id
    agent = Agent(
        title_id=title_id,
        code=f"referrer-wait-{uuid4().hex[:10]}",
        first_name="Goal",
        last_name="Waiter",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.mark.asyncio
async def test_human_question_reminds_once_pauses_then_answer_resumes(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    agent = await _new_agent(db)
    tool = Tool(
        code=f"goal-wait-{uuid4().hex[:8]}",
        label="Goal wait test",
        description="",
        connection_schema={},
    )
    db.add(tool)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    goal = await make_goal(
        title="Obtain a human decision",
        description="Ask once, remind once, and wait without spamming.",
        agent_id=agent.id,
        referrer_type=GoalReferrerType.MESSENGER,
        referrer_connection_id=connection.id,
        referrer_user_id="human-referrer",
        referrer_display_name="Human Referrer",
        referrer_platform="test_messenger",
        referrer_max_reminders=1,
        cycle_delay_seconds=0,
        status=GoalStatus.ACTIVE,
    )
    parent = Task(
        label="Goal cycle",
        objective="Advance the Goal",
        status=TaskStatus.EXEC,
        agent_id=agent.id,
        goal=goal,
        data={"language": "en"},
    )
    db.add_all([goal, parent])
    await db.commit()

    messenger = _FakeMessenger(tool.id)
    monkeypatch.setattr(
        "app.messenger.service.messenger_for_agent_connection",
        AsyncMock(return_value=messenger),
    )
    monkeypatch.setattr(goal_service, "assert_referrer_available", AsyncMock())
    monkeypatch.setattr("app.task.runner.go_next", lambda *_args, **_kwargs: None)

    result = await referrer_wait.ask_human_referrer(
        task_id=parent.id,
        agent_id=agent.id,
        question="Which delivery option should I use?",
        language="en",
    )

    assert "Question sent" in result
    assert len(messenger.sent) == 1
    wait = await db.scalar(select(Task).where(Task.parent_id == parent.id))
    assert wait is not None
    marker = collab.await_marker(wait)
    assert marker is not None
    assert marker["kind"] == referrer_wait.REFERRER_WAIT_KIND
    assert marker["reminders_sent"] == 0
    interaction = await db.scalar(
        select(Interaction).where(
            Interaction.kind == referrer_wait.REFERRER_INTERACTION_KIND
        )
    )
    assert interaction is not None
    assert interaction.user_id == "human-referrer"
    goal_id = goal.id
    parent_id = parent.id
    wait_id = wait.id
    interaction_id = interaction.id
    interaction_reference = interaction.reference
    tool_id = tool.id
    agent_id = agent.id

    # Executor finalization discovers the awaited child and suspends the Goal Task.
    assert parent.status == TaskStatus.EXEC
    assert await collab.suspend_on_pending_children(parent) is True
    await task_service.save(parent)
    assert task_service.is_paused_for(parent, task_service.PAUSE_AWAIT)

    first_due = datetime.now(timezone.utc)
    marker = {
        **marker,
        "next_action_at": (first_due - timedelta(seconds=1)).isoformat(),
    }
    wait.data = {**(wait.data or {}), collab.AWAIT_KEY: marker}
    await task_service.save(wait)

    assert await referrer_wait.process_due_referrer_wait(first_due) is True
    assert len(messenger.sent) == 2
    assert "Reminder 1/1" in messenger.sent[-1][1]
    db.expire_all()
    wait = await db.get(Task, wait_id)
    assert wait is not None
    marker = collab.await_marker(wait)
    assert marker is not None and marker["reminders_sent"] == 1

    final_due = first_due + timedelta(days=1, seconds=1)
    marker = {
        **marker,
        "next_action_at": (final_due - timedelta(seconds=1)).isoformat(),
    }
    wait.data = {**(wait.data or {}), collab.AWAIT_KEY: marker}
    await task_service.save(wait)

    assert await referrer_wait.process_due_referrer_wait(final_due) is True
    assert len(messenger.sent) == 2
    db.expire_all()
    goal = await db.get(Goal, goal_id)
    parent = await db.get(Task, parent_id)
    assert goal is not None and parent is not None
    assert goal.status == GoalStatus.PAUSED
    assert goal.pause_reason == referrer_wait.REFERRER_NO_RESPONSE_PAUSE_REASON
    assert task_service.is_paused_for(parent, task_service.PAUSE_USER)

    incoming = Message(
        id=uuid4(),
        connection_id=cast(int, None),
        tool_id=tool_id,
        platform="test_messenger",
        remote_message_id="human-answer",
        direction="inbound",
        text=f"Use option B #{interaction_reference}",
        created_at=datetime.now(timezone.utc),
    )
    incoming.sender = MessengerUser(
        id=uuid4(),
        tool_id=tool_id,
        external_id="human-referrer",
        display_name="Human Referrer",
    )
    incoming.recipient = MessengerUser(
        id=uuid4(),
        tool_id=tool_id,
        external_id="goal-agent",
        agent_id=agent_id,
        is_ai=True,
    )
    incoming.room = Room(
        id=UUID("00000000-0000-0000-0000-000000000201"),
        connection_id=0,
        external_id="dm-human-referrer",
        label="Human Referrer",
        kind="direct",
        conversation_type="text",
    )
    resolution = await interactions.resolve_from_message(incoming, agent_id=agent_id)

    assert resolution is not None
    db.expire_all()
    goal = await db.get(Goal, goal_id)
    parent = await db.get(Task, parent_id)
    wait = await db.get(Task, wait_id)
    interaction = await db.get(Interaction, interaction_id)
    assert goal is not None and parent is not None and wait is not None
    assert interaction is not None
    assert goal.status == GoalStatus.ACTIVE
    assert goal.pause_reason is None
    assert parent.paused is False
    assert wait.status == TaskStatus.SUCCESS
    assert interaction.status == "RESOLVED"
    assert "Use option B" in collab.collab_context(parent)
