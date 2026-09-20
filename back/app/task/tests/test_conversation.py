from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.task import get_conversation_followup, get_conversation_scope
from app.task.models import Task, TaskStatus


@pytest.mark.asyncio
async def _agents(db: AsyncSession) -> tuple[Agent, Agent]:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Conversation test {suffix}", gender="X")
    db.add(title)
    await db.flush()
    owner = Agent(
        title_id=title.id,
        first_name="Alice",
        last_name="Conversation",
        code=f"conversation-a-{suffix}",
        agent_driver="internal",
    )
    peer = Agent(
        title_id=title.id,
        first_name="Bob",
        last_name="Conversation",
        code=f"conversation-b-{suffix}",
        agent_driver="internal",
    )
    db.add_all([owner, peer])
    await db.flush()
    return owner, peer


@pytest.mark.asyncio
async def test_followup_uses_exact_room_platform_and_agent(
    db: AsyncSession,
) -> None:
    owner, peer = await _agents(db)
    started_at = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)
    current = Task(
        label="Current",
        objective="Deploy the service.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        message_platform="nextcloud_talk",
        message_group_id="room-42",
        created_at=started_at,
    )
    wrong_room = Task(
        label="Other room",
        objective="This objective belongs to another conversation.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        message_platform="nextcloud_talk",
        message_group_id="room-99",
        created_at=started_at + timedelta(minutes=1),
    )
    wrong_agent = Task(
        label="Other agent",
        objective="This objective belongs to another agent.",
        status=TaskStatus.SUCCESS,
        agent_id=peer.id,
        message_platform="nextcloud_talk",
        message_group_id="room-42",
        created_at=started_at + timedelta(minutes=2),
    )
    expected = Task(
        label="Follow-up",
        objective="The deployment failed because the port was occupied.",
        status=TaskStatus.ERROR,
        agent_id=owner.id,
        message_platform="nextcloud_talk",
        message_group_id="room-42",
        created_at=started_at + timedelta(minutes=3),
    )
    db.add_all([current, wrong_room, wrong_agent, expected])
    await db.commit()

    followup = await get_conversation_followup(current)

    assert followup is not None
    assert followup.task_id == expected.id
    assert followup.objective == expected.objective


@pytest.mark.asyncio
async def test_followup_supports_api_conversation_id(
    db: AsyncSession,
) -> None:
    owner, _peer = await _agents(db)
    started_at = datetime(2026, 6, 2, 9, 0, tzinfo=timezone.utc)
    current = Task(
        label="Current API task",
        objective="Generate the archive.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        message_platform="openai",
        data={"conversation_id": "conv-42"},
        created_at=started_at,
    )
    expected = Task(
        label="API follow-up",
        objective="The archive is valid.",
        status=TaskStatus.SUCCESS,
        agent_id=owner.id,
        message_platform="openai",
        data={"conversation_id": "conv-42"},
        created_at=started_at + timedelta(minutes=1),
    )
    db.add_all([current, expected])
    await db.commit()

    followup = await get_conversation_followup(current)

    assert followup is not None
    assert followup.task_id == expected.id


def test_scope_exists_for_first_task_and_separates_connections() -> None:
    common = {
        "label": "First conversation task",
        "objective": "Remember the conversation topic.",
        "status": TaskStatus.SUCCESS,
        "agent_id": 42,
        "message_platform": "matrix",
        "message_group_id": "!room:example",
    }
    first = Task(**common, messenger_connection_id=7)
    same = Task(**common, messenger_connection_id=7)
    other_connection = Task(**common, messenger_connection_id=8)

    first_scope = get_conversation_scope(first)
    same_scope = get_conversation_scope(same)
    other_scope = get_conversation_scope(other_connection)

    assert first_scope is not None
    assert same_scope is not None
    assert other_scope is not None
    assert first_scope.kind == "messenger"
    assert first_scope.channel == "matrix"
    assert first_scope.scope_hash == same_scope.scope_hash
    assert first_scope.scope_hash != other_scope.scope_hash
    assert "!room:example" not in first_scope.scope_hash
