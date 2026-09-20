import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.models import Agent, Title
from app.connection.models import Connection
from app.tools.models import Tool
from bridge.mail import dbadmin
from bridge.mail.models import MailOutboundDelivery
from core.dbadmin import DbAdminRegistry, SchemaTransitionSet


def test_agent_snapshot_action_only_targets_the_new_column() -> None:
    applicable = SchemaTransitionSet(
        added_columns=frozenset({"mail_outbound_deliveries.agent_id"})
    )
    unrelated = SchemaTransitionSet(
        added_columns=frozenset({"mail_outbound_deliveries.subject"})
    )

    assert dbadmin._introduces_agent_snapshot(applicable)  # pyright: ignore[reportPrivateUsage]
    assert not dbadmin._introduces_agent_snapshot(unrelated)  # pyright: ignore[reportPrivateUsage]
    registry = DbAdminRegistry()
    dbadmin.register_dbadmin(registry)
    assert [action.key for action in registry.actions] == [
        "bridge.mail.backfill_outbound_agent_snapshots"
    ]


@pytest.mark.asyncio
async def test_agent_snapshot_backfill_is_idempotent(db: AsyncSession) -> None:
    title = Title(label="Agent", gender="N")
    tool = Tool(code="mail-dbadmin-test", label="Mail")
    db.add_all([title, tool])
    await db.flush()
    agent = Agent(
        title_id=title.id,
        first_name="Audit",
        last_name="Agent",
        code="mail-dbadmin-agent",
    )
    db.add(agent)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
    db.add(connection)
    await db.flush()
    delivery = MailOutboundDelivery(
        connection_id=connection.id,
        agent_id=None,
        agent_label="",
        sender_address="agent@example.test",
        idempotency_key="legacy-mail",
        payload_fingerprint="a" * 64,
        rfc_message_id="<legacy@example.test>",
        ai_disclosure_version="galaris-ai-v1",
        status="sent",
    )
    db.add(delivery)
    await db.flush()
    transitions = SchemaTransitionSet(
        added_columns=frozenset({"mail_outbound_deliveries.agent_id"})
    )

    await dbadmin._backfill_agent_snapshots(db, transitions)  # pyright: ignore[reportPrivateUsage]
    await dbadmin._backfill_agent_snapshots(db, transitions)  # pyright: ignore[reportPrivateUsage]

    await db.refresh(delivery)
    assert delivery.agent_id == agent.id
    assert delivery.agent_label == "Audit Agent"
    assert await dbadmin._all_connected_deliveries_have_agents(  # pyright: ignore[reportPrivateUsage]
        db, transitions
    )
