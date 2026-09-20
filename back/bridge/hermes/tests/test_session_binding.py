from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from bridge.hermes import session_binding


def _task(**overrides):
    values = {
        "id": "task-id",
        "agent_id": 7,
        "message_platform": "talk",
        "message_group_id": "room-42",
        "messenger_connection_id": 11,
        "data": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_conversation_scope_distinguishes_platforms_and_supports_openai_id():
    talk = session_binding.conversation_scope(_task())
    other_connection = session_binding.conversation_scope(
        _task(messenger_connection_id=22)
    )
    matrix = session_binding.conversation_scope(_task(message_platform="matrix"))
    openai = session_binding.conversation_scope(
        _task(message_platform="openai", message_group_id=None, data={"conversation_id": "conv-1"})
    )

    assert talk is not None and talk.key == "connection:11:room:room-42"
    assert other_connection is not None and other_connection.hash != talk.hash
    assert matrix is not None and matrix.hash != talk.hash
    assert openai is not None and openai.key == "conversation:conv-1"


def test_initial_id_is_opaque_and_stable_key_does_not_expose_room():
    scope = session_binding.conversation_scope(_task())
    assert scope is not None
    session_id = session_binding._initial_session_id(scope)
    key = session_binding.stable_session_key(_task())

    assert session_id.startswith("galaris_")
    assert "room-42" not in session_id
    assert key.startswith("galaris_key_")
    assert "room-42" not in key
    assert key != session_binding.stable_session_key(
        _task(messenger_connection_id=22)
    )


def test_effective_session_id_follows_terminal_rotation_only():
    assert session_binding.effective_session_id(
        "room-42", "run.completed", {"session_id": " compressed-tip "}
    ) == "compressed-tip"
    assert session_binding.effective_session_id(
        "room-42", "assistant.delta", {"session_id": "stale-or-untrusted"}
    ) == "room-42"
@pytest.mark.asyncio
async def test_get_or_create_returns_persisted_rotation_after_restart(monkeypatch):
    db = MagicMock()
    db.scalar = AsyncMock(return_value="hermes-compressed-tip")
    db.commit = AsyncMock()
    monkeypatch.setattr(session_binding, "get_db", lambda: db)

    session_id = await session_binding.get_or_create_session_id(_task())

    assert session_id == "hermes-compressed-tip"
    db.scalar.assert_awaited_once()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_or_create_persists_new_binding(monkeypatch):
    insert_result = MagicMock()
    insert_result.scalar_one_or_none.return_value = "galaris_new"
    db = MagicMock()
    db.execute = AsyncMock(return_value=insert_result)
    db.scalar = AsyncMock(return_value=None)
    db.commit = AsyncMock()
    monkeypatch.setattr(session_binding, "get_db", lambda: db)
    monkeypatch.setattr(
        session_binding,
        "_claim_legacy_binding",
        AsyncMock(return_value=None),
    )

    assert await session_binding.get_or_create_session_id(_task()) == "galaris_new"
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_follow_rotation_uses_compare_and_swap(monkeypatch):
    update_result = MagicMock(rowcount=1)
    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)
    db.execute = AsyncMock(return_value=update_result)
    db.commit = AsyncMock()
    monkeypatch.setattr(session_binding, "get_db", lambda: db)

    changed = await session_binding.follow_rotation(_task(), "room-42", "compressed-tip")

    assert changed is True
    db.execute.assert_awaited_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_background_task_keeps_isolated_session(monkeypatch):
    monkeypatch.setattr(
        session_binding,
        "get_db",
        lambda: pytest.fail("background task must not access a conversation binding"),
    )
    task = _task(message_group_id=None, data=None)
    session_id = await session_binding.get_or_create_session_id(task)
    assert session_id.startswith("galaris_task_")
    assert session_id == await session_binding.get_or_create_session_id(task)
