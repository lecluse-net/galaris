from uuid import UUID, uuid4

import pytest
from sqlalchemy import select

from app.memory.tests.conftest import agents  # noqa: F401
from app.tools.models import Tool
from app.connection.models import Connection, ConnectionParam
from app.task import Task
from app.webhook import functions


@pytest.mark.asyncio
async def test_redelivery_returns_same_task_but_distinct_connection_and_payload_are_respected(db, agents, monkeypatch):
    tool = Tool(code=f"delivery-{uuid4().hex}", label="Webhook", listener_config={"connection_key": "channel"})
    db.add(tool)
    await db.flush()
    for index, agent in enumerate(agents):
        connection = Connection(tool_id=tool.id, agent_id=agent.id, active=True)
        db.add(connection)
        await db.flush()
        db.add(ConnectionParam(connection_id=connection.id, param_name="channel", param_value=str(index)))
    await db.commit()
    monkeypatch.setattr(functions.runner, "go_next", lambda *_: None)
    payload = {"channel": "0", "label": "one event"}
    first = await functions.webhook_make_task(tool.code, payload, delivery_id="event-42")
    replay = await functions.webhook_make_task(tool.code, payload, delivery_id="event-42")
    assert replay == first
    with pytest.raises(functions.WebhookIdentityConflict):
        await functions.webhook_make_task(tool.code, {**payload, "label": "different"}, delivery_id="event-42")
    other = await functions.webhook_make_task(tool.code, {**payload, "channel": "1"}, delivery_id="event-42")
    assert other != first
    distinct = await functions.webhook_make_task(tool.code, payload)
    assert distinct not in {first, other}
    assert (await db.scalars(select(Task).where(Task.id == UUID(first)))).one().label == "one event"
