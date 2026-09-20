from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest

from app.conversation import activity_facade


class _Rows:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def all(self) -> list[object]:
        return self._rows


@pytest.mark.asyncio
async def test_activity_summary_correlates_every_round_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    room_id = uuid4()
    input_message_id = uuid4()
    output_message_id = uuid4()
    topic_id = uuid4()
    row = SimpleNamespace(
        id=round_id,
        room_id=room_id,
        topic_id=topic_id,
        status="SUCCEEDED",
        effect_started=False,
        execution_result={},
        created_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    database = Mock()
    database.scalar = AsyncMock(return_value=1)
    database.scalars = AsyncMock(
        side_effect=[_Rows([row]), _Rows([])],
    )
    database.execute = AsyncMock(
        return_value=_Rows(
            [
                (round_id, input_message_id, "input"),
                (round_id, output_message_id, "output"),
            ]
        )
    )
    monkeypatch.setattr(activity_facade, "get_db", lambda: database)

    result = await activity_facade.list_room_activity(room_id)

    assert result.total == 1
    assert result.items[0].message_ids == [input_message_id, output_message_id]
    assert result.items[0].response_message_id == output_message_id
    assert result.items[0].topic_id == row.topic_id


@pytest.mark.asyncio
async def test_activity_detail_projects_tools_and_redacts_private_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    round_id = uuid4()
    room_id = uuid4()
    row = SimpleNamespace(
        id=round_id,
        room_id=room_id,
        status="SUCCEEDED",
        last_error=None,
        execution_result={
            "prompt": "private user prompt",
            "system_prompt": "private system prompt",
            "success": True,
            "execution_time": 1.25,
            "cost": 0.02,
            "result": "Voici la réponse finale.",
            "tools_used": ["thinking", "search_web"],
            "messages": [
                {
                    "type": "tool",
                    "tool_name": "thinking",
                    "content": "Je vérifie les contraintes; token=abcdefghijklmnop",
                    "success": True,
                },
                {
                    "type": "text",
                    "content": "rejected narration before a tool call",
                    "success": True,
                },
                {
                    "type": "tool",
                    "tool_name": "search_web",
                    "tool_arguments": {
                        "query": "actualité locale",
                        "api_key": "super-secret",
                    },
                    "tool_result": {
                        "count": 2,
                        "authorization": "Bearer should-not-leak",
                    },
                    "content": "2 résultats; bearer abcdefghijklmnop",
                    "success": True,
                    "execution_time": 0.4,
                },
            ],
            "metadata": {"memory": "private"},
        },
        created_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
    )
    database = Mock()
    database.scalar = AsyncMock(return_value=row)
    monkeypatch.setattr(activity_facade, "get_db", lambda: database)

    detail = await activity_facade.get_room_activity_detail(room_id, round_id)

    assert detail is not None
    assert detail.result == "Voici la réponse finale."
    assert [interaction.kind for interaction in detail.interactions] == [
        "thinking",
        "tool_call",
        "ai_message",
    ]
    thinking, search, answer = detail.interactions
    assert thinking.content == "Je vérifie les contraintes; token=[redacted]"
    assert thinking.arguments == {}
    assert search.tool_name == "search_web"
    assert search.arguments == {
        "query": "actualité locale",
        "api_key": "[redacted]",
    }
    assert search.result["authorization"] == "[redacted]"
    assert "abcdefghijklmnop" not in search.content
    assert answer.content == "Voici la réponse finale."
    serialized = detail.model_dump_json()
    assert "Je vérifie les contraintes" in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "private system prompt" not in serialized
    assert "rejected narration" not in serialized
    assert "super-secret" not in serialized


@pytest.mark.asyncio
async def test_activity_detail_returns_none_outside_requested_room(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = Mock()
    database.scalar = AsyncMock(return_value=None)
    monkeypatch.setattr(activity_facade, "get_db", lambda: database)

    assert await activity_facade.get_room_activity_detail(uuid4(), uuid4()) is None
