from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.task import collab, task_service
from app.task.models import Task, TaskStatus

_TERMINAL = (TaskStatus.SUCCESS, TaskStatus.ERROR)


def _task(**kw: Any) -> Task:
    defaults: dict[str, Any] = {
        "id": uuid4(),
        "label": "Task",
        "objective": "Objective",
        "status": TaskStatus.EXEC,
        "paused": False,
        "ai": False,
        "cost": 0.0,
        "effort": "standard",
        "auto_approve": False,
        "parent_id": None,
        "agent_id": 7,
        "data": None,
    }
    defaults.update(kw)
    return Task(**defaults)


def _await_child(parent_id: Any, peer: str, status: TaskStatus, **kw: Any) -> Task:
    """Build a wait subtask, open and suspended for non-terminal statuses, otherwise resolved."""
    open_ = status not in _TERMINAL
    data: dict[str, Any] = {
        collab.AWAIT_KEY: {"peer_user_id": peer, "peer_display": peer.title(), "room_id": "room-1"}
    }
    if open_:
        data["pause_reasons"] = [task_service.PAUSE_AWAIT]
    return _task(
        parent_id=parent_id,
        status=TaskStatus.DISPATCH if open_ else status,
        paused=open_,
        message_group_id="room-1",
        data=data,
        **kw,
    )


def _await_parent(**kw: Any) -> Task:
    """Requester paused on ``await`` with DISPATCH as its resume point."""
    data: dict[str, Any] = {"pause_reasons": [task_service.PAUSE_AWAIT]}
    data.update(kw.pop("data", None) or {})
    return _task(status=TaskStatus.DISPATCH, paused=True, data=data, **kw)


# Correlation.

@pytest.mark.asyncio
async def test_is_open_exchange_matches_peer(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task()
    child = _await_child(parent.id, "lyra", TaskStatus.PAUSE)
    monkeypatch.setattr(collab, "_open_awaits", AsyncMock(return_value=[child]))

    assert await collab.is_open_exchange(agent_id=7, room_id="room-1", peer_user_id="lyra") is True
    assert await collab.is_open_exchange(agent_id=7, room_id="room-1", peer_user_id="bob") is False


@pytest.mark.asyncio
async def test_awaited_for_incoming_returns_await(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task()
    child = _await_child(parent.id, "lyra", TaskStatus.PAUSE)
    open_awaits = AsyncMock(return_value=[child])
    monkeypatch.setattr(collab, "_open_awaits", open_awaits)

    found = await collab.awaited_for_incoming(
        sender_agent_id=7,
        connection_id=19,
        room_id="room-1",
        recipient_user_id="lyra",
    )
    assert found is child
    open_awaits.assert_awaited_with(7, "room-1", 19)
    assert await collab.awaited_for_incoming(
        sender_agent_id=7,
        connection_id=19,
        room_id="room-1",
        recipient_user_id="other",
    ) is None


# Resolution when the peer task completes.

@pytest.mark.asyncio
async def test_resolve_from_peer_task_closes_await_with_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent_id = uuid4()
    await_id = uuid4()
    await_child = _await_child(parent_id, "lyra", TaskStatus.PAUSE, id=await_id)
    peer_task = _task(feedback="Here is my complete report.", status=TaskStatus.SUCCESS,
                      data={collab.RESOLVES_KEY: str(await_id)})

    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=await_child))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    fan_in = AsyncMock()
    monkeypatch.setattr(collab, "maybe_fan_in", fan_in)

    await collab.resolve_from_peer_task(peer_task)

    assert await_child.status == TaskStatus.SUCCESS
    assert await_child.feedback == "Here is my complete report."
    assert (await_child.data or {})[collab.RESOLVED_BY_KEY] == str(peer_task.id)
    fan_in.assert_awaited_once_with(parent_id)


@pytest.mark.asyncio
async def test_resolve_from_peer_task_marks_error_on_peer_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await_id = uuid4()
    await_child = _await_child(uuid4(), "lyra", TaskStatus.PAUSE, id=await_id)
    peer_task = _task(status=TaskStatus.ERROR, data={collab.RESOLVES_KEY: str(await_id)})

    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=await_child))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    monkeypatch.setattr(collab, "maybe_fan_in", AsyncMock())

    await collab.resolve_from_peer_task(peer_task)
    assert await_child.status == TaskStatus.ERROR


@pytest.mark.asyncio
async def test_resolve_from_peer_task_noop_without_stamp(monkeypatch: pytest.MonkeyPatch) -> None:
    get_by_id = AsyncMock()
    monkeypatch.setattr(collab.task_service, "get_by_id", get_by_id)
    await collab.resolve_from_peer_task(_task(status=TaskStatus.SUCCESS))
    get_by_id.assert_not_awaited()


# ── Fan-in ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_maybe_fan_in_waits_until_all_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _await_parent()
    done = _await_child(parent.id, "lyra", TaskStatus.SUCCESS, feedback="CR Lyra")
    pending = _await_child(parent.id, "bob", TaskStatus.PAUSE)
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(collab.task_service, "get_children", AsyncMock(return_value=[done, pending]))
    update = AsyncMock()
    monkeypatch.setattr(collab.task_service, "update", update)

    await collab.maybe_fan_in(parent.id)
    assert parent.paused is True  # One wait remains open, so the parent stays paused.
    update.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [TaskStatus.SUCCESS, TaskStatus.ERROR])
async def test_maybe_fan_in_never_reopens_terminal_parent(
    monkeypatch: pytest.MonkeyPatch,
    status: TaskStatus,
) -> None:
    parent = _task(
        status=status,
        paused=True,
        data={"pause_reasons": [task_service.PAUSE_AWAIT]},
    )
    get_children = AsyncMock()
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(collab.task_service, "get_children", get_children)
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())

    await collab.maybe_fan_in(parent.id)

    assert parent.status == status
    assert parent.paused is True
    get_children.assert_not_awaited()


@pytest.mark.asyncio
async def test_maybe_fan_in_reexecutes_and_counts_round(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _await_parent(data={collab.ROUNDS_KEY: 1, "language": "en"})
    c1 = _await_child(parent.id, "lyra", TaskStatus.SUCCESS, feedback="CR Lyra")
    c2 = _await_child(parent.id, "bob", TaskStatus.ERROR, feedback="no response")
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(collab.task_service, "get_children", AsyncMock(return_value=[c1, c2]))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    recorder = _CallRecorder()
    monkeypatch.setattr("app.task.runner.go_next", recorder)

    await collab.maybe_fan_in(parent.id)

    assert parent.status == TaskStatus.DISPATCH
    assert parent.paused is False  # Folded wait releases the suspension.
    assert parent.data is not None
    ctx = parent.data[collab.COLLAB_CONTEXT_KEY]
    assert "CR Lyra" in ctx
    assert "⚠️" in ctx  # Bob's failure is reported as a problem.
    assert "Do not repeat or delegate requests" in ctx
    assert parent.data[collab.ROUNDS_KEY] == 2
    assert recorder.called_with == parent.id


# ── Filets scheduler ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_resume_expired_awaits_fails_stale_and_fans_in(monkeypatch: pytest.MonkeyPatch) -> None:
    parent_id = uuid4()
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    expired = _await_child(parent_id, "lyra", TaskStatus.PAUSE)
    expired.data = {collab.AWAIT_KEY: {"peer_display": "Lyra", "deadline": past}}
    fresh = _await_child(uuid4(), "bob", TaskStatus.PAUSE)
    fresh.data = {collab.AWAIT_KEY: {"peer_display": "Bob", "deadline": future}}

    monkeypatch.setattr(collab, "_open_await_children", AsyncMock(return_value=[expired, fresh]))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    fan_in = AsyncMock()
    monkeypatch.setattr(collab, "maybe_fan_in", fan_in)

    await collab.resume_expired_awaits()

    assert expired.status == TaskStatus.ERROR
    assert "Lyra" in (expired.feedback or "")
    assert collab.TIMED_OUT_KEY in (expired.data or {})  # Timestamped for late catch-up.
    assert fresh.paused is True  # Not expired, so it remains suspended.
    fan_in.assert_awaited_once_with(parent_id)


# Late response from a peer after expiration.

@pytest.mark.asyncio
async def test_timed_out_await_for_late_reply_matches_within_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(timezone.utc)

    def _s(**data_extra: Any) -> Task:
        data = {collab.AWAIT_KEY: {"peer_user_id": "lyra", "peer_display": "Lyra"}}
        data.update(data_extra)
        return _task(message_group_id="room-1", data=data)

    recent = _s(**{collab.TIMED_OUT_KEY: now.isoformat()})
    too_old = _s(**{collab.TIMED_OUT_KEY: (now - timedelta(
        seconds=collab.LATE_ANSWER_GRACE_SECONDS + 60)).isoformat()})
    already_done = _s(**{collab.TIMED_OUT_KEY: now.isoformat(), collab.COMPLEMENT_SENT_KEY: True})
    not_expired = _await_child(uuid4(), "lyra", TaskStatus.PAUSE)  # Open, without timed_out.

    rows = [too_old, already_done, not_expired, recent]
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))
    monkeypatch.setattr(collab, "get_db", lambda: SimpleNamespace(execute=AsyncMock(return_value=result)))

    found = await collab.timed_out_await_for_late_reply(
        agent_id=7, room_id="room-1", peer_user_id="lyra")
    assert found is recent  # Only a recent, expired, incomplete wait matches.
    other = await collab.timed_out_await_for_late_reply(
        agent_id=7, room_id="room-1", peer_user_id="bob")
    assert other is None  # Different peer.


@pytest.mark.asyncio
async def test_relay_late_answer_notifies_requester_once(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(message_group_id="nicolas-room", message_platform="talk")
    s = _task(parent_id=parent.id, objective="Are you joining us for lunch?",
              data={collab.AWAIT_KEY: {"peer_user_id": "lyra"}, collab.TIMED_OUT_KEY: "x"})
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    update = AsyncMock()
    monkeypatch.setattr(collab.task_service, "update", update)

    sent: list[tuple[str, str]] = []

    class _Msgr:
        async def send_to_room(self, room: str, text: str) -> None:
            sent.append((room, text))

    import app.messenger as messenger_mod
    monkeypatch.setattr(messenger_mod, "resolve_task_messaging",
                        AsyncMock(return_value=(_Msgr(), "self")))

    await collab.relay_late_answer(s, "Yes, I am coming!", "Lyra")

    assert sent and sent[0][0] == "nicolas-room"           # Relayed to the requester's room.
    assert "Lyra" in sent[0][1] and "Yes, I am coming" in sent[0][1]
    assert (s.data or {}).get(collab.COMPLEMENT_SENT_KEY) is True  # anti-double
    update.assert_awaited()

    # A deleted parent prevents relaying.
    sent.clear()
    gone = _task(message_group_id="nicolas-room", message_platform="talk")
    gone.soft_delete()
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=gone))
    await collab.relay_late_answer(s, "answer", "Lyra")
    assert sent == []


# Fast-peer race: the wait resolves before the initial run ends.

def _fanned(child: Task) -> Task:
    child.data = {**(child.data or {}), collab.FANNED_IN_KEY: True}
    return child


@pytest.mark.asyncio
async def test_has_unsynthesized_children_covers_resolved_but_unfanned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _task()
    # An open wait is not synthesized.
    monkeypatch.setattr(
        collab.task_service, "get_children",
        AsyncMock(return_value=[_await_child(parent.id, "lyra", TaskStatus.PAUSE)]),
    )
    assert await collab.has_unsynthesized_children(parent.id) is True
    # A resolved but not-yet-folded wait from a fast peer is still not synthesized. This is the
    # exact case that has_pending_awaits previously missed.
    monkeypatch.setattr(
        collab.task_service, "get_children",
        AsyncMock(return_value=[_await_child(parent.id, "lyra", TaskStatus.SUCCESS)]),
    )
    assert await collab.has_unsynthesized_children(parent.id) is True
    # A resolved and folded wait is synthesized, leaving nothing blocked.
    monkeypatch.setattr(
        collab.task_service, "get_children",
        AsyncMock(return_value=[_fanned(_await_child(parent.id, "lyra", TaskStatus.SUCCESS))]),
    )
    assert await collab.has_unsynthesized_children(parent.id) is False


# Delegated task_run subtasks using the call-stack model.

def _delegated_child(parent_id: Any, status: TaskStatus, **kw: Any) -> Task:
    """A delegated task_run subtask has delegated but no await_marker."""
    return _task(parent_id=parent_id, status=status,
                 data={task_service.DELEGATED_KEY: True}, **kw)


@pytest.mark.asyncio
async def test_suspend_on_pending_children_uses_child_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(status=TaskStatus.EXEC)
    child = _delegated_child(parent.id, TaskStatus.EXEC)
    monkeypatch.setattr(collab.task_service, "get_children", AsyncMock(return_value=[child]))

    suspended = await collab.suspend_on_pending_children(parent)

    assert suspended is True
    assert parent.status == TaskStatus.DISPATCH  # Resume by re-executing.
    assert task_service.is_paused_for(parent, task_service.PAUSE_CHILD) is True
    assert task_service.is_paused_for(parent, task_service.PAUSE_AWAIT) is False


@pytest.mark.asyncio
async def test_suspend_on_pending_children_recovers_parent_after_stream_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _task(status=TaskStatus.EXEC, feedback="Client disconnected during streaming")
    await_child = _await_child(parent.id, "orion", TaskStatus.SUCCESS, feedback="vert fluo")
    delegated_child = _delegated_child(
        parent.id,
        TaskStatus.SUCCESS,
        feedback="color not provided",
    )
    monkeypatch.setattr(
        collab.task_service,
        "get_children",
        AsyncMock(return_value=[await_child, delegated_child]),
    )

    suspended = await collab.suspend_on_pending_children(parent)

    assert suspended is True
    assert parent.status == TaskStatus.DISPATCH
    assert task_service.is_paused_for(parent, task_service.PAUSE_AWAIT) is True
    assert task_service.is_paused_for(parent, task_service.PAUSE_CHILD) is True


@pytest.mark.asyncio
async def test_maybe_fan_in_resumes_on_delegated_child(monkeypatch: pytest.MonkeyPatch) -> None:
    parent = _task(status=TaskStatus.DISPATCH, paused=True, data={"pause_reasons": ["child"]})
    child = _delegated_child(parent.id, TaskStatus.SUCCESS, feedback="deliverable ready")
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(collab.task_service, "get_children", AsyncMock(return_value=[child]))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    recorder = _CallRecorder()
    monkeypatch.setattr("app.task.runner.go_next", recorder)

    await collab.maybe_fan_in(parent.id)

    assert parent.status == TaskStatus.DISPATCH
    assert parent.paused is False  # Child suspension released; the task is runnable.
    assert parent.data is not None
    assert "deliverable ready" in parent.data[collab.COLLAB_CONTEXT_KEY]
    assert collab._is_fanned_in(child) is True
    assert recorder.called_with == parent.id


@pytest.mark.asyncio
async def test_maybe_fan_in_marks_awaits_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = _await_parent()
    child = _await_child(parent.id, "lyra", TaskStatus.SUCCESS, feedback="CR Lyra")
    monkeypatch.setattr(collab.task_service, "get_by_id", AsyncMock(return_value=parent))
    monkeypatch.setattr(collab.task_service, "get_children", AsyncMock(return_value=[child]))
    monkeypatch.setattr(collab.task_service, "update", AsyncMock())
    recorder = _CallRecorder()
    monkeypatch.setattr("app.task.runner.go_next", recorder)

    await collab.maybe_fan_in(parent.id)

    # First pass: re-execute and stamp the folded wait.
    assert parent.status == TaskStatus.DISPATCH
    assert parent.paused is False
    assert collab._is_fanned_in(child) is True
    assert recorder.called_with == parent.id

    # Second pass for the backstop/fast-peer case: it is suspended again, but the wait is already
    # folded, so there is no new execution.
    task_service.suspend(parent, task_service.PAUSE_AWAIT)
    recorder.called_with = None
    await collab.maybe_fan_in(parent.id)
    assert parent.paused is True
    assert recorder.called_with is None


class _CallRecorder:
    def __init__(self) -> None:
        self.called_with: Any = None

    def __call__(self, task_id: Any, *args: Any, **kwargs: Any) -> None:
        self.called_with = task_id
