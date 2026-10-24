"""Monthly accounting preserves provenance, scope and history without per-call probes."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import event, insert, text

from app.agent import Agent, Title
from app.connection import Connection
from app.conversation import ConversationProcessLink, ConversationRound
from app.llm import LLMCall
from app.messenger import Room
from app.process import ProcessDefinition, ProcessRun
from app.task import Task, TaskStatus
from app.tools import ToolModel
from app.topic import service
from app.topic.models import Topic


async def seed_usage(db, *, repetitions=1, unrelated_tasks=0):
    title = Title(label="Synthetic attribution", gender="X")
    tool = ToolModel(code=uuid4().hex, label="Synthetic attribution engine", connection_schema={})
    topics = [Topic(title=f"Synthetic attribution {index}",
        created_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc)) for index in range(4)]
    db.add_all([title, tool, *topics])
    await db.flush()
    agents = [Agent(title_id=title.id, first_name=f"Synthetic {index}", last_name="Attribution", code=uuid4().hex)
        for index in range(3)]
    db.add_all(agents)
    await db.flush()
    connection = Connection(tool_id=tool.id, agent_id=agents[1].id, active=True)
    tasks = [Task(label="Synthetic attribution task", status=TaskStatus.SUCCESS, agent_id=agents[index].id,
        topic_id=topics[index].id) for index in range(2)]
    definition = ProcessDefinition(agent_id=agents[2].id, tool_id=tool.id,
        engine_process_id=uuid4().hex, label="Synthetic attribution process")
    db.add_all([connection, definition, *tasks])
    await db.flush()
    room = Room(connection_id=connection.id, external_id=uuid4().hex, label="Synthetic attribution room",
        kind="direct", conversation_type="text")
    db.add(room)
    await db.flush()
    rounds = [ConversationRound(room_id=room.id, topic_id=topics[index + 2].id, status="SUCCEEDED")
        for index in range(2)]
    runs = [ProcessRun(process_id=definition.id, launcher_agent_id=agents[2].id, engine_code="fake",
        task_id=tasks[1].id if index == 0 else None, correlation_id=uuid4().hex, callback_token="synthetic")
        for index in range(2)]
    db.add_all([*rounds, *runs])
    await db.flush()
    db.add_all([ConversationProcessLink(round_id=rounds[0].id, process_run_id=run.id,
        action_key=uuid4().hex) for run in runs])
    cases = [
        dict(task_id=tasks[0].id, process_run_id=runs[0].id, conversation_round_id=rounds[1].id, agent_id=agents[2].id),
        dict(task_id=tasks[0].id, process_run_id=runs[0].id, conversation_round_id=rounds[1].id),
        dict(process_run_id=runs[0].id, conversation_round_id=rounds[1].id),
        dict(process_run_id=runs[1].id, conversation_round_id=rounds[1].id),
        dict(conversation_round_id=rounds[1].id),
        dict(process_run_id=runs[1].id),
    ]
    for index, case in enumerate(cases):
        await db.execute(insert(LLMCall), [{**case, "cost": 99.0, "inference_cost": float(index + 1),
            "started_at": datetime(2026, 7, 5, 12, tzinfo=timezone.utc)} for _ in range(repetitions)])
    # This month must also respect agent attribution and removed conversation links.
    db.add(LLMCall(process_run_id=runs[1].id, inference_cost=7.0,
        started_at=datetime(2026, 2, 15, 12, tzinfo=timezone.utc)))
    if unrelated_tasks:
        await db.execute(insert(Task), [{"label": f"Synthetic unrelated task {index}",
            "status": TaskStatus.SUCCESS, "agent_id": agents[0].id} for index in range(unrelated_tasks)])
    await db.commit()
    return SimpleNamespace(agents=agents, topics=topics, tasks=tasks, room=room,
        connection=connection, rounds=rounds, runs=runs)


BASE = [(0, 2), (0, 0), (1, 1), (2, 1), (3, 1), (2, 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("change,attributions", [
    ("none", BASE),
    ("task", [(1, 2), (1, 1), *BASE[2:]]),
    ("process_task", [*BASE[:2], (2, 1), *BASE[3:]]),
    ("run", [*BASE[:2], (2, 1), *BASE[3:]]),
    ("conversation_run", [*BASE[:5], (2, None)]),
    ("launch_round", [*BASE[:3], (3, 1), (3, 1), (None, 2)]),
    ("direct_round", [*BASE[:2], (1, 2), (2, 2), (None, None), (2, 2)]),
    ("room", [*BASE[:2], (1, 2), (2, 2), (3, None), (2, 2)]),
    ("connection", BASE),
    ("task_without_topic", [(1, 2), (1, 0), *BASE[2:]]),
    ("process_task_without_topic", [*BASE[:2], (2, 1), *BASE[3:]]),
    ("topic", BASE),
])
async def test_monthly_attribution_preserves_priorities_scope_and_reference_lifecycles(db, monkeypatch, change, attributions):
    monkeypatch.setenv("TZ", "Europe/Paris")
    data = await seed_usage(db)
    if change in {"launch_round", "direct_round"}:
        await db.delete(data.rounds[0 if change == "launch_round" else 1])
    elif change == "connection":
        data.connection.active = False
    elif change in {"task_without_topic", "process_task_without_topic"}:
        data.tasks[0 if change == "task_without_topic" else 1].topic_id = None
    elif change != "none":
        {"task": data.tasks[0], "process_task": data.tasks[1], "run": data.runs[0],
            "conversation_run": data.runs[1], "room": data.room, "topic": data.topics[0]}[change].soft_delete()
    await db.commit()
    for allowed in [None, set(), {0}, {1}, {2}]:
        page = await service.list_page(skip=0, limit=50, search=None, month="2026-07",
            agent_ids=None if allowed is None else [data.agents[index].id for index in allowed])
        assert page.total == (3 if change == "topic" else 4)
        assert {item.id for item in page.items} == {
            topic.id for index, topic in enumerate(data.topics) if change != "topic" or index != 0}
        for topic_index, topic in enumerate(data.topics):
            if change == "topic" and topic_index == 0:
                continue
            expected = [index + 1 for index, (assigned_topic, assigned_agent) in enumerate(attributions)
                if assigned_topic == topic_index and (allowed is None or assigned_agent in allowed)]
            item = next(item for item in page.items if item.id == topic.id)
            assert item.llm_calls == len(expected), (change, allowed, topic_index)
            assert item.inference_cost == pytest.approx(sum(expected)), (change, allowed, topic_index)
        february_agent = None if change == "conversation_run" else 2
        expect_february = change != "launch_round" and (allowed is None or february_agent in allowed)
        assert ("2026-02" in page.available_months) is expect_february


@pytest.mark.asyncio
@pytest.mark.parametrize("scoped", [False, True])
async def test_monthly_usage_bounds_database_work_for_a_growing_call_history(db, scoped):
    data = await seed_usage(db, repetitions=200, unrelated_tasks=1000)
    for name in ("llm_calls", "tasks", "process_runs", "conversation_rounds", "conversation_process_links",
                 "messenger_rooms", "connections", "topics"):
        await db.execute(text(f"ANALYZE {name}"))
    connection = await db.connection()
    captured = []

    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.startswith("SELECT") and "llm_calls" in statement:
            captured.append((statement, parameters))

    event.listen(connection.sync_connection, "before_cursor_execute", capture)
    try:
        page = await service.list_page(skip=0, limit=50, search=None, month="2026-07",
            agent_ids=[data.agents[1].id] if scoped else None)
    finally:
        event.remove(connection.sync_connection, "before_cursor_execute", capture)
    assert sum(item.llm_calls for item in page.items) == (600 if scoped else 1200)
    assert sum(item.inference_cost for item in page.items) == (2400 if scoped else 4200)
    assert captured
    buffers = 0
    for statement, parameters in captured:
        result = await connection.exec_driver_sql(
            "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + statement, parameters)
        plan = result.scalar_one()[0]["Plan"]
        buffers += plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0)
    # Count database work rather than asserting a fragile wall-clock duration or SQL shape.
    assert buffers <= 2 * 1201, f"Attribution must avoid repeated indexed probes per call: {buffers} buffers"
