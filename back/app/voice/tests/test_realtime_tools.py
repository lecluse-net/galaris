from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.voice import realtime_tools as realtime_tools_module


@asynccontextmanager
async def _db_session() -> AsyncIterator[None]:
    yield None


def test_realtime_voice_exposes_only_conversation_control_tools() -> None:
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id="voice-room",
        transport_kind="nextcloud_talk",
        language="fr",
    )

    assert {tool.definition.name for tool in tools} == {
        "voice_call_stop",
        "memory_search",
        "memory_remember",
        "conversation_task_list",
        "conversation_task_submit",
        "conversation_task_status",
        "process_list",
        "process_get",
        "conversation_process_start",
    }


@pytest.mark.asyncio
async def test_realtime_voice_stop_arms_a_real_hangup() -> None:
    hangup_requested = asyncio.Event()
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id="voice-room",
        transport_kind="nextcloud_talk",
        language="fr",
        hangup_requested=hangup_requested,
    )

    output = await realtime_tools_module.execute_realtime_tool(
        tools,
        name="voice_call_stop",
        arguments="{}",
    )

    assert json.loads(output) == {
        "ok": True,
        "result": {"hangup_requested": True},
    }
    assert hangup_requested.is_set()


@pytest.mark.asyncio
async def test_realtime_memory_search_keeps_the_exact_contact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory
    from app.memory import service as memory_service

    topic_id = uuid4()
    topic_item_id = uuid4()
    contact_item_id = uuid4()
    recall = AsyncMock(
        return_value=SimpleNamespace(
            query="plage",
            mode="lexical",
            degraded=False,
            hits=[],
        )
    )
    monkeypatch.setattr(realtime_tools_module, "get_db_session", _db_session)
    monkeypatch.setattr(
        memory_service,
        "projected_topic_item_id",
        AsyncMock(return_value=topic_item_id),
    )
    monkeypatch.setattr(memory, "search_memory_detailed", recall)
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id="voice-room",
        transport_kind="nextcloud_talk",
        language="fr",
        topic_id=topic_id,
        contact_memory_item_id=contact_item_id,
    )

    await realtime_tools_module.execute_realtime_tool(
        tools,
        name="memory_search",
        arguments=json.dumps({"query": "plage"}),
    )

    assert recall.await_args.args[0] == "plage"
    assert recall.await_args.kwargs["topic_item_id"] == topic_item_id
    assert recall.await_args.kwargs["contact_item_id"] == contact_item_id
    assert recall.await_args.kwargs["limit"] is None


@pytest.mark.asyncio
async def test_realtime_memory_remember_keeps_exact_round_and_contact_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.memory as memory
    from app.memory import service as memory_service

    round_id = uuid4()
    topic_id = uuid4()
    topic_item_id = uuid4()
    contact_item_id = uuid4()
    memory_id = uuid4()
    acquisition_id = uuid4()
    acquire = AsyncMock(
        return_value=SimpleNamespace(
            acquisition_id=acquisition_id,
            memory_id=memory_id,
            created=True,
            status="stored",
        )
    )
    seal = AsyncMock()
    monkeypatch.setattr(realtime_tools_module, "get_db_session", _db_session)
    monkeypatch.setattr(
        memory_service,
        "projected_topic_item_id",
        AsyncMock(return_value=topic_item_id),
    )
    monkeypatch.setattr(memory, "acquire_memory", acquire)
    monkeypatch.setattr(memory, "ensure_topic_contact_memory_scope", seal)
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id=str(uuid4()),
        transport_kind="nextcloud_talk",
        language="fr",
        topic_id=topic_id,
        contact_memory_item_id=contact_item_id,
        voice_session_id=uuid4(),
        current_round_id=lambda: round_id,
    )

    output = await realtime_tools_module.execute_realtime_tool(
        tools,
        name="memory_remember",
        arguments=json.dumps(
            {
                "title": "Préférence de Nicolas",
                "content": "Nicolas préfère les réponses courtes.",
                "memory_type": "semantic",
                "keywords": ["réponses", "préférence"],
            }
        ),
    )

    assert json.loads(output)["result"] == {
        "acquisition_id": str(acquisition_id),
        "created": True,
        "status": "stored",
        "memory_id": str(memory_id),
    }
    acquisition = acquire.await_args.args[0]
    assert acquisition.source_kind == "conversation_round"
    assert acquisition.source_ref == f"conversation_round:{round_id}"
    assert acquisition.metadata["contact_item_id"] == str(contact_item_id)
    assert acquisition.metadata["topic_item_id"] == str(topic_item_id)
    seal.assert_awaited_once_with(
        owner_agent_id=7,
        topic_item_id=topic_item_id,
        contact_item_id=contact_item_id,
        memory_item_id=memory_id,
        source_kind="conversation_round",
        source_ref=f"conversation_round:{round_id}",
    )


@pytest.mark.asyncio
async def test_realtime_voice_starts_process_as_background_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.process import process_service

    start = AsyncMock(
        return_value=SimpleNamespace(
            deduplicated=False,
            model_dump=lambda **_kwargs: {
                "run_id": "run-1",
                "status": "queued",
            },
        )
    )
    monkeypatch.setattr(realtime_tools_module, "get_db_session", _db_session)
    monkeypatch.setattr(process_service, "start_process", start)
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id="voice-room",
        transport_kind="nextcloud_talk",
        language="fr",
    )

    output = await realtime_tools_module.execute_realtime_tool(
        tools,
        name="conversation_process_start",
        arguments=json.dumps(
            {"workflow_id": "daily-report", "input": {"date": "today"}}
        ),
    )

    assert json.loads(output)["result"]["created"] is True
    start.assert_awaited_once_with(
        agent_id=7,
        workflow_id="daily-report",
        input_data={"date": "today"},
        wait_for_completion=False,
        task_id=None,
        runtime="internal",
    )


@pytest.mark.asyncio
async def test_realtime_task_list_reuses_the_canonical_room_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.conversation as conversation

    room_id = uuid4()
    projection = (
        {
            "task_id": str(uuid4()),
            "objective": "O" * 250,
            "operational_state": "PAUSED",
            "state_since": "2026-08-24T10:00+02:00",
        },
    )
    snapshot = AsyncMock(return_value=projection)
    monkeypatch.setattr(realtime_tools_module, "get_db_session", _db_session)
    monkeypatch.setattr(conversation, "linked_work_snapshot", snapshot)
    tools = realtime_tools_module.realtime_tools(
        agent_id=7,
        conversation_id=str(room_id),
        transport_kind="nextcloud_talk",
        language="fr",
    )

    output = await realtime_tools_module.execute_realtime_tool(
        tools,
        name="conversation_task_list",
        arguments="{}",
    )

    assert json.loads(output)["result"]["items"] == list(projection)
    snapshot.assert_awaited_once_with(room_id)
