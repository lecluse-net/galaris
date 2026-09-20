from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import dbadmin_composition
from app.agent.models import Agent, Title
from app.connection.models import Connection, ConnectionParam
from app.conversation.models import (
    ConversationRound,
    ConversationRoundAttempt,
    ConversationRoundMessage,
    ConversationTaskLink,
)
from app.messenger.models import Message, MessengerUser, Room
from app.messenger.user_service import reconcile_nextcloud_agent_identities
from app.task.models import Task, TaskStatus
from app.tools.models import Tool
from core.dbadmin import SchemaTransitionSet


def test_legacy_admission_action_is_tied_to_durable_task_key() -> None:
    assert dbadmin_composition._adds_durable_messenger_task_key(  # pyright: ignore[reportPrivateUsage]
        SchemaTransitionSet(added_columns=frozenset({"tasks.messenger_message_id"}))
    )
    assert not dbadmin_composition._adds_durable_messenger_task_key(  # pyright: ignore[reportPrivateUsage]
        SchemaTransitionSet()
    )


@pytest.mark.asyncio
async def test_legacy_admission_backfill_is_idempotent(db: AsyncSession) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Admission {suffix}", gender="X")
    tool = Tool(
        code=f"admission-{suffix}",
        label="Admission",
        description="",
        connection_schema={},
    )
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Admission",
        last_name="Test",
        code=f"admission-{suffix}",
        agent_driver="internal",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    room = Room(
        connection_id=connection.id,
        external_id=f"legacy-room-{suffix}",
        label="Legacy room",
        conversation_type="text",
    )
    db.add(room)
    await db.flush()
    now = datetime.now(timezone.utc)
    message = Message(
        id=uuid4(),
        connection_id=connection.id,
        tool_id=tool.id,
        platform="nextcloud_talk",
        remote_message_id=f"legacy-{suffix}",
        direction="inbound",
        status="received",
        text="Legacy input",
        messenger_room_id=room.id,
        created_at=now - timedelta(hours=2),
    )
    db.add(message)
    await db.flush()
    first = Task(
        label="Original admission",
        status=TaskStatus.SUCCESS,
        data={"message_id": str(message.id)},
        created_at=now - timedelta(hours=2) + timedelta(minutes=1),
    )
    duplicate = Task(
        label="Replay admission",
        status=TaskStatus.CREATE,
        data={"message_id": str(message.id)},
        created_at=now,
    )
    conversation_task = Task(
        label="Conversation replay task",
        status=TaskStatus.EXEC,
        created_at=now,
    )
    round_ = ConversationRound(
        room_id=room.id,
        language="fr",
        status="RUNNING",
        delivery_state="PENDING",
        attempt_count=1,
        created_at=now,
    )
    db.add_all([first, duplicate, conversation_task, round_])
    await db.flush()
    db.add_all(
        [
            ConversationRoundMessage(
                round_id=round_.id,
                message_id=message.id,
                role="input",
                sequence=1,
            ),
            ConversationRoundAttempt(
                round_id=round_.id,
                attempt_number=1,
                worker_id="old-worker",
                lease_token=uuid4(),
                status="RUNNING",
            ),
            ConversationTaskLink(
                round_id=round_.id,
                task_id=conversation_task.id,
                action_key="legacy-replay",
            ),
        ]
    )
    await db.commit()
    transitions = SchemaTransitionSet(
        added_columns=frozenset({"tasks.messenger_message_id"})
    )

    await dbadmin_composition._backfill_messenger_admissions(  # pyright: ignore[reportPrivateUsage]
        db,
        transitions,
    )
    await db.commit()
    await db.refresh(message)
    await db.refresh(first)
    await db.refresh(duplicate)
    await db.refresh(conversation_task)
    await db.refresh(round_)

    assert message.status == "admitted"
    assert first.messenger_message_id == message.id
    assert duplicate.messenger_message_id is None
    assert duplicate.status is TaskStatus.ERROR
    assert duplicate.cancel_requested is True
    assert (duplicate.data or {}).get("quarantined_messenger_replay") is True
    assert conversation_task.status is TaskStatus.ERROR
    assert conversation_task.cancel_requested is True
    assert round_.status == "CANCELLED"
    assert round_.delivery_state == "SKIPPED"
    assert await dbadmin_composition._legacy_messenger_admissions_are_closed(  # pyright: ignore[reportPrivateUsage]
        db,
        transitions,
    )

    await dbadmin_composition._backfill_messenger_admissions(  # pyright: ignore[reportPrivateUsage]
        db,
        transitions,
    )
    await db.commit()
    await db.refresh(first)
    assert first.messenger_message_id == message.id


@pytest.mark.asyncio
async def test_nextcloud_agent_identity_reconciliation_is_exact_and_idempotent(
    db: AsyncSession,
) -> None:
    suffix = uuid4().hex[:10]
    title = Title(label=f"Nextcloud identity {suffix}", gender="X")
    tool = Tool(
        code=f"nextcloud-identity-{suffix}",
        label="Nextcloud Talk",
        description="",
        connection_schema={
            "params": {"nextcloud_login": {"type": "string"}},
        },
        messenger_config={
            "service": "nextcloud_talk",
            "param_map": {"login": "nextcloud_login"},
        },
    )
    db.add_all([title, tool])
    await db.flush()
    agents = [
        Agent(
            title_id=title.id,
            first_name=name,
            last_name="Test",
            code=f"{name.lower()}-identity-{suffix}",
            agent_driver="internal",
        )
        for name in ("Lyra", "Orion", "Ambiguous", "Duplicate")
    ]
    db.add_all(agents)
    await db.flush()
    connections = [
        Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        for agent in agents
    ]
    db.add_all(connections)
    await db.flush()
    db.add_all(
        [
            ConnectionParam(
                connection_id=connections[0].id,
                param_name="nextcloud_login",
                param_value="lyra",
            ),
            ConnectionParam(
                connection_id=connections[1].id,
                param_name="nextcloud_login",
                param_value="orion",
            ),
            ConnectionParam(
                connection_id=connections[2].id,
                param_name="nextcloud_login",
                param_value="shared-login",
            ),
            ConnectionParam(
                connection_id=connections[3].id,
                param_name="nextcloud_login",
                param_value="shared-login",
            ),
        ]
    )
    identities = [
        MessengerUser(
            tool_id=tool.id,
            external_id="lyra",
            display_name="Lyra d'Exemple",
            agent_id=agents[1].id,
            is_ai=True,
        ),
        MessengerUser(
            tool_id=tool.id,
            external_id="orion",
            display_name="Orion Test",
            agent_id=None,
            is_ai=False,
        ),
        MessengerUser(
            tool_id=tool.id,
            external_id="unknown",
            display_name="Unknown",
            agent_id=agents[0].id,
            is_ai=True,
        ),
        MessengerUser(
            tool_id=tool.id,
            external_id="shared-login",
            display_name="Ambiguous",
            agent_id=agents[2].id,
            is_ai=True,
        ),
    ]
    db.add_all(identities)
    await db.flush()

    first = await reconcile_nextcloud_agent_identities()
    await db.flush()

    assert first.users_scanned == 4
    assert first.links_created == 1
    assert first.links_corrected == 1
    assert first.links_cleared == 2
    assert identities[0].agent_id == agents[0].id
    assert identities[1].agent_id == agents[1].id
    assert identities[2].agent_id is None
    assert identities[3].agent_id is None

    second = await reconcile_nextcloud_agent_identities()
    await db.flush()

    assert second.users_scanned == 4
    assert second.links_created == 0
    assert second.links_corrected == 0
    assert second.links_cleared == 0
