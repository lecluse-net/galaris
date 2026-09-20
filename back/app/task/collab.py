"""Blocking peer requests for inter-agent collaboration.

There is no dedicated collaboration tool. When an agent sends a private message to another AI
agent through ``messenger_send_message_to_user``, messaging routes the request here. The question
is sent and an awaited child ``S`` is created below the current task ``T``. ``T`` cannot finish
until every awaited child resolves. It resumes with peer results in context, synthesizes them,
and communicates the outcome to the original requester. The objective remains anchored through
``parent_id`` and ``source_task_id``.

Correlation is robust to conversational chatter. On the requester side, ``S`` stores its peer,
room, and deadline in ``data[AWAIT_KEY]``. On the peer side, the incoming question creates a task
stamped with ``data[RESOLVES_KEY] = S.id``. Completion of that peer task resolves ``S``; a raw
acknowledgement cannot accidentally close it. Scheduler timeout and fan-in backstops cover silent
peers and concurrent completion races.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Sequence, cast
from uuid import UUID
import json

from loguru import logger
from sqlalchemy import select

from core.database import get_db
from core.i18n import default_language, is_supported, render_prompt, t

from . import task_service
from .models import Task, TaskStatus

# Centralized keys for ``task.data``.
AWAIT_KEY = "awaiting_reply"        # On S: peer, room, and deadline.
RESOLVES_KEY = "resolves_await"     # On peer task: awaited S UUID.
OPEN_EXCHANGE_KEY = "open_exchange_await"  # On requester input: still-open S UUID.
RESOLVED_BY_KEY = "resolved_by_task_id"  # On S: peer task that resolved it.
COLLAB_CONTEXT_KEY = "collab_context"  # On parent: aggregated prompt context.
ROUNDS_KEY = "collab_rounds"        # On parent: completed collaboration cycles.
FANNED_IN_KEY = "fanned_in"         # On S: result already folded into parent.
TIMED_OUT_KEY = "timed_out_at"      # On S: ISO timeout timestamp.
COMPLEMENT_SENT_KEY = "late_complement_sent"  # On S: late answer already relayed.

_TERMINAL = (TaskStatus.SUCCESS, TaskStatus.ERROR)
# Keep a timed-out child eligible during this window so a late peer answer can be relayed.
LATE_ANSWER_GRACE_SECONDS = 7200  # 2 h


def _task_language(task: Task) -> str:
    """Return the durable task language, falling back to the configured default."""

    raw = str(_data(task).get("language") or "").strip().lower()
    return raw if is_supported(raw) else default_language()


def _message(task: Task, key: str, **values: Any) -> str:
    """Render a collaboration message in the task's durable language."""

    return render_prompt(t(f"task_collab.{key}", _task_language(task)), **values)


# ─────────────────────────────────────────────────────────────────────────────
# Typed accessors for task data markers
# ─────────────────────────────────────────────────────────────────────────────

def _data(task: Task) -> dict[str, Any]:
    return task.data if isinstance(task.data, dict) else {}


def await_marker(task: Task) -> Optional[dict[str, Any]]:
    """Return the await marker for child ``S``, or ``None`` for a regular task."""
    marker: Any = _data(task).get(AWAIT_KEY)
    return cast("dict[str, Any]", marker) if isinstance(marker, dict) else None


def _is_fanned_in(task: Task) -> bool:
    """Return whether a coordination child was already folded into its parent."""
    return bool(_data(task).get(FANNED_IN_KEY))


def _is_delegated(task: Task) -> bool:
    """Return whether ``task`` is a delegated child awaited by its creator."""
    return bool(_data(task).get(task_service.DELEGATED_KEY))


def is_coordination_child(task: Task) -> bool:
    """Return whether a parent awaits this child's result before resuming."""
    return await_marker(task) is not None or _is_delegated(task)


def resolves_await_id(task: Task) -> Optional[UUID]:
    """Return the awaited UUID that completion of this peer task must resolve."""
    raw = _data(task).get(RESOLVES_KEY)
    if not raw:
        return None
    try:
        return UUID(str(raw))
    except (TypeError, ValueError):
        return None


def collab_context(task: Task) -> str:
    """Return the peer-results block to inject into the resume prompt."""
    return str(_data(task).get(COLLAB_CONTEXT_KEY) or "").strip()


def collab_rounds(task: Task) -> int:
    """Return the number of completed collaboration cycles."""
    try:
        return int(_data(task).get(ROUNDS_KEY, 0) or 0)
    except (TypeError, ValueError):
        return 0


# ─────────────────────────────────────────────────────────────────────────────
# Request dispatch: materialize the await child
# ─────────────────────────────────────────────────────────────────────────────

async def dispatch_question(
    *,
    parent: Task,
    peer_user_id: str,
    peer_display: str,
    room_id: str,
    platform: Optional[str],
    question: str,
    connection_id: int | None = None,
) -> Task:
    """Create awaited child ``S`` after the question has been sent.

    ``S`` remains suspended for reason ``await`` until the peer task finishes or its deadline
    is handled by ``resume_expired_awaits``.
    """
    from .schemas import TaskCreate
    from core.params import runtime_settings

    asked_at = datetime.now(timezone.utc)
    deadline = asked_at + timedelta(
        seconds=runtime_settings.TASK_ASK_AGENT_TIMEOUT_SECONDS
    )
    child = await task_service.create(
        TaskCreate(
            label=_message(
                parent, "request_label", peer=peer_display or peer_user_id
            ),
            objective=question,
            agent_id=parent.agent_id,
            parent_id=parent.id,
            source_task_id=parent.id,
            status=TaskStatus.DISPATCH,
            paused=True,
            ai=False,
            messenger_connection_id=(
                connection_id
                if connection_id is not None
                else parent.messenger_connection_id
            ),
            message_platform=platform,
            message_group_id=room_id,
            data={
                "language": _task_language(parent),
                "pause_reasons": [task_service.PAUSE_AWAIT],
                AWAIT_KEY: {
                    "peer_user_id": str(peer_user_id),
                    "peer_display": str(peer_display or peer_user_id),
                    "room_id": str(room_id),
                    "asked_at": asked_at.isoformat(),
                    "deadline": deadline.isoformat(),
                },
            },
        )
    )
    logger.info(
        "ask_agent: await {} created below {} (peer={}, room={})",
        child.id, parent.id, peer_user_id, room_id,
    )
    return child


async def dispatch_process_wait(
    *,
    parent: Task,
    run_id: UUID,
    process_label: str,
    timeout_seconds: int,
) -> Task:
    """Create an opt-in ProcessRun await without creating an LLM execution task."""
    from .schemas import TaskCreate
    asked_at = datetime.now(timezone.utc)
    deadline = asked_at + timedelta(seconds=max(60, timeout_seconds))
    language = _task_language(parent)
    label = render_prompt(t("process.await_label", language), label=process_label)
    objective = render_prompt(
        t("process.await_objective", language), label=process_label, run_id=run_id
    )
    child = await task_service.create(TaskCreate(
        label=label,
        objective=objective,
        agent_id=parent.agent_id,
        parent_id=parent.id,
        source_task_id=parent.id,
        status=TaskStatus.DISPATCH,
        paused=True,
        ai=False,
        messenger_connection_id=parent.messenger_connection_id,
        message_platform=parent.message_platform,
        message_group_id=parent.message_group_id,
        data={
            "language": language,
            "pause_reasons": [task_service.PAUSE_AWAIT],
            AWAIT_KEY: {
                "kind": "process",
                "run_id": str(run_id),
                "process_label": process_label,
                "peer_display": process_label,
                "asked_at": asked_at.isoformat(),
                "deadline": deadline.isoformat(),
            },
        },
    ))
    logger.info("process: await {} created below {} for run {}", child.id, parent.id, run_id)
    return child


async def resolve_process_await(
    *,
    await_task_id: UUID,
    process_label: str,
    run_id: UUID,
    status: str,
    output: dict[str, Any] | None,
    error: str | None,
) -> None:
    """Resolve an await linked to a process run, then reuse collaboration fan-in."""
    child = await task_service.get_by_id(await_task_id)
    marker = await_marker(child) if child is not None else None
    if child is None or marker is None or marker.get("kind") != "process":
        return
    if child.status in _TERMINAL:
        # A previous delivery may have committed the child before parent fan-in.
        await maybe_fan_in(child.parent_id)
        return
    from app.task.workflow import TaskEvent, transition
    if status == "success":
        transition(child, TaskEvent.COORDINATION_SUCCEEDED)
        child.feedback = render_prompt(
            t("process.await_success", _task_language(child)),
            label=process_label,
            run_id=run_id,
            status=status,
            output=json.dumps(output or {}, ensure_ascii=False, default=str),
        )
    else:
        transition(child, TaskEvent.COORDINATION_FAILED)
        child.feedback = render_prompt(
            t("process.await_error", _task_language(child)),
            label=process_label,
            run_id=run_id,
            status=status,
            error=error or status,
        )
    child.data = {**_data(child), RESOLVED_BY_KEY: f"process:{run_id}"}
    task_service.clear_pauses(child)
    await task_service.save(child)
    await maybe_fan_in(child.parent_id)


# ─────────────────────────────────────────────────────────────────────────────
# Correlation of open awaits for an agent and room
# ─────────────────────────────────────────────────────────────────────────────

async def _open_awaits(
    agent_id: int, room_id: str, connection_id: int | None = None
) -> list[Task]:
    """Return open suspended await children for an agent in a room."""
    db = get_db()
    query = (
        select(Task)
        .where(
            Task.agent_id == agent_id,
            Task.message_group_id == room_id,
            Task.paused.is_(True),
        )
        .order_by(Task.created_at.asc())
    )
    if connection_id is not None:
        query = query.where(Task.messenger_connection_id == connection_id)
    rows: Sequence[Task] = (await db.execute(Task.histo_filter(query))).scalars().all()
    return [t for t in rows if await_marker(t) is not None]


async def open_exchange_await(
    *,
    agent_id: int,
    room_id: str,
    peer_user_id: str,
    connection_id: int | None = None,
) -> Optional[Task]:
    """Return an open await from ``agent_id`` to a peer in a room, when present.

    The requester uses this to annotate an incoming turn. The dispatcher still decides whether
    to process the message, while peer task completion resolves the await.
    """
    for task in await _open_awaits(agent_id, room_id, connection_id):
        marker = await_marker(task) or {}
        if str(marker.get("peer_user_id")) == peer_user_id:
            return task
    return None


async def is_open_exchange(
    *,
    agent_id: int,
    room_id: str,
    peer_user_id: str,
    connection_id: int | None = None,
) -> bool:
    """Return whether an agent has an open await for a peer in a room."""
    return await open_exchange_await(
        agent_id=agent_id,
        room_id=room_id,
        peer_user_id=peer_user_id,
        connection_id=connection_id,
    ) is not None


async def awaited_for_incoming(
    *,
    sender_agent_id: int,
    room_id: str,
    recipient_user_id: str,
    connection_id: int | None = None,
    platform: str | None = None,
) -> Optional[Task]:
    """Return the await answered by an incoming peer task, or ``None``."""
    for task in await _open_awaits(sender_agent_id, room_id, connection_id):
        if platform is not None and task.message_platform != platform:
            continue
        marker = await_marker(task) or {}
        if str(marker.get("peer_user_id")) == recipient_user_id:
            return task
    return None


# ─────────────────────────────────────────────────────────────────────────────
# Late-answer recovery after an await deadline
# ─────────────────────────────────────────────────────────────────────────────

async def timed_out_await_for_late_reply(
    *,
    agent_id: int,
    room_id: str,
    peer_user_id: str,
    connection_id: int | None = None,
) -> Optional[Task]:
    """Return a recent timed-out await eligible for one late peer response."""
    from core.params import runtime_settings

    db = get_db()
    now = datetime.now(timezone.utc)
    grace_cutoff = now - timedelta(seconds=LATE_ANSWER_GRACE_SECONDS)
    # Bound the query by creation time, timeout duration, and a generous grace margin.
    created_cutoff = now - timedelta(
        seconds=runtime_settings.TASK_ASK_AGENT_TIMEOUT_SECONDS + LATE_ANSWER_GRACE_SECONDS + 3600
    )
    query = (
        select(Task)
        .where(
            Task.agent_id == agent_id,
            Task.message_group_id == room_id,
            Task.created_at > created_cutoff,
        )
        .order_by(Task.created_at.desc())
    )
    if connection_id is not None:
        query = query.where(Task.messenger_connection_id == connection_id)
    rows: Sequence[Task] = (await db.execute(Task.histo_filter(query))).scalars().all()
    for s in rows:
        marker = await_marker(s)
        if marker is None or str(marker.get("peer_user_id")) != peer_user_id:
            continue
        data = _data(s)
        if data.get(COMPLEMENT_SENT_KEY):
            continue  # Late answer already relayed.
        raw = data.get(TIMED_OUT_KEY)
        if not raw:
            continue  # Not expired through the timeout path.
        try:
            expired_at = datetime.fromisoformat(str(raw))
        except (TypeError, ValueError):
            continue
        if expired_at < grace_cutoff:
            continue  # Outside the grace window.
        return s
    return None


async def relay_late_answer(s: Task, answer_text: str, peer_display: str) -> None:
    """Relay a late peer answer to the original requester exactly once.

    This recovery path is defensive: failures are logged and never break message processing.
    """
    try:
        answer = (answer_text or "").strip()
        if not answer or s.parent_id is None:
            return
        parent = await task_service.get_by_id(s.parent_id)
        if parent is None or parent.deleted_at is not None or not parent.message_group_id:
            return

        from app.messenger import resolve_task_messaging

        messenger, _self_id = await resolve_task_messaging(parent)
        if messenger is None:
            return
        question = str(s.objective or "").strip()
        key = "late_complement_with_question" if question else "late_complement"
        text = _message(
            parent,
            key,
            peer=peer_display,
            question=question[:120],
            answer=answer,
        )
        await messenger.send_to_room(parent.message_group_id, text)
        s.data = {**_data(s), COMPLEMENT_SENT_KEY: True}
        await task_service.save(s)
        logger.info("ask_agent: late peer answer relayed to requester (await {})", s.id)
    except Exception:
        logger.exception(
            "ask_agent: failed to relay late peer answer (await {})", getattr(s, "id", "?")
        )


# ─────────────────────────────────────────────────────────────────────────────
# Peer task completion resolves the await
# ─────────────────────────────────────────────────────────────────────────────

async def resolve_from_peer_task(peer_task: Task) -> None:
    """Resolve an await from peer task completion and attempt parent fan-in."""
    await_id = resolves_await_id(peer_task)
    if await_id is None:
        return
    child = await task_service.get_by_id(await_id)
    if child is None or await_marker(child) is None or child.status in _TERMINAL:
        return
    if peer_task.status == TaskStatus.ERROR:
        from app.task.workflow import TaskEvent, transition

        transition(child, TaskEvent.COORDINATION_FAILED)
        child.feedback = _message(child, "peer_failed")
    else:
        from app.task.workflow import TaskEvent, transition

        transition(child, TaskEvent.COORDINATION_SUCCEEDED)
        child.feedback = (peer_task.feedback or "").strip() or _message(
            child, "empty_response"
        )
    child.data = {**_data(child), RESOLVED_BY_KEY: str(peer_task.id)}
    task_service.clear_pauses(child)  # A terminal await is no longer suspended.
    await task_service.save(child)
    logger.info("ask_agent: await {} resolved by peer task {}", child.id, peer_task.id)
    await maybe_fan_in(child.parent_id)


async def resolve_external_await(
    await_task_id: UUID,
    response: str,
    *,
    failed: bool = False,
) -> bool:
    """Resolve a non-agent await and reuse the regular collaboration fan-in path."""

    child = await task_service.get_by_id(await_task_id)
    if child is None or await_marker(child) is None or child.status in _TERMINAL:
        return False
    from app.task.workflow import TaskEvent, transition

    transition(
        child,
        TaskEvent.COORDINATION_FAILED if failed else TaskEvent.COORDINATION_SUCCEEDED,
    )
    child.feedback = response.strip()
    task_service.clear_pauses(child)
    await task_service.save(child)
    await maybe_fan_in(child.parent_id)
    return True


# ─────────────────────────────────────────────────────────────────────────────
# Fan-in: resume the parent once every coordination child is terminal.
# ─────────────────────────────────────────────────────────────────────────────

async def has_unsynthesized_children(parent_id: UUID) -> bool:
    """Return whether a parent has a coordination child not yet synthesized.

    This covers both collaboration awaits and delegated children, including a child that
    finishes before its parent's initial run ends.
    """
    for child in await task_service.get_children(parent_id):
        if is_coordination_child(child) and not _is_fanned_in(child):
            return True
    return False


async def suspend_on_pending_children(task: Task) -> bool:
    """Suspend an executing parent when coordination children still need fan-in.

    The resume point is DISPATCH and pause reasons identify collaboration or delegation. This
    call-stack model prevents the Task from becoming terminal until children return, including
    when the last LLM call failed after creating them. Resumption synthesizes results without
    replaying tool effects.
    """
    children = await task_service.get_children(task.id)
    fresh = [c for c in children if is_coordination_child(c) and not _is_fanned_in(c)]
    if not fresh:
        return False
    from app.task.workflow import TaskEvent, transition

    # This transition happens before EXECUTION_SUCCEEDED/FAILED. A terminal Task is never used
    # as a provisional coordination state and therefore never needs to be reopened.
    transition(task, TaskEvent.INTERRUPT_EXECUTION)
    if any(await_marker(c) is not None for c in fresh):
        task_service.suspend(task, task_service.PAUSE_AWAIT)
    if any(_is_delegated(c) for c in fresh):
        task_service.suspend(task, task_service.PAUSE_CHILD)
    return True


async def maybe_fan_in(parent_id: Optional[UUID]) -> None:
    """Resume a parent once all of its coordination children are terminal.

    Results are injected into ``data[COLLAB_CONTEXT_KEY]`` before the parent returns to DISPATCH
    without invoking the planner again. Markers make repeated online and backstop fan-in safe.
    """
    if parent_id is None:
        return
    parent = await task_service.get_by_id(parent_id)
    # Resume only internal awaits. A human-held or deleted parent must remain untouched.
    if (
        parent is None
        or parent.deleted_at is not None
        # Legacy rows can carry stale internal pause markers even after completion. The
        # scheduler backstop must treat a terminal phase as authoritative and never reopen it.
        or parent.status in _TERMINAL
        or not (
            task_service.is_paused_for(parent, task_service.PAUSE_AWAIT)
            or task_service.is_paused_for(parent, task_service.PAUSE_CHILD)
        )
        or task_service.is_held_by_user(parent)
    ):
        return
    children = await task_service.get_children(parent_id)
    coord = [c for c in children if is_coordination_child(c)]
    if not coord or any(c.status not in _TERMINAL for c in coord):
        return  # At least one coordination child is still open.
    fresh = [c for c in coord if not _is_fanned_in(c)]
    if not fresh:
        return  # Everything was folded during an earlier cycle.

    block = _message(parent, "resume_prompt") + "\n\n" + "\n\n".join(
        _render_await_result(c) for c in fresh
    )
    data = dict(_data(parent))
    prior = str(data.get(COLLAB_CONTEXT_KEY) or "").strip()
    data[COLLAB_CONTEXT_KEY] = f"{prior}\n\n{block}".strip() if prior else block
    data[ROUNDS_KEY] = collab_rounds(parent) + 1
    parent.data = data
    from app.task.workflow import TaskEvent, transition

    transition(parent, TaskEvent.RESUME_COLLABORATION)
    transition(parent, TaskEvent.ROUTE_TO_EXECUTION)
    task_service.release(parent, task_service.PAUSE_AWAIT)  # Clear internal suspension.
    task_service.release(parent, task_service.PAUSE_CHILD)
    await task_service.save(parent)

    # Stamp folded children so a fast-child race or scheduler backstop cannot synthesize twice.
    for child in fresh:
        child.data = {**_data(child), FANNED_IN_KEY: True}
        await task_service.save(child)

    from app.task.runner import go_next

    logger.info("ask_agent: all awaits for {} resolved; resuming (cycle {})",
                parent.id, data[ROUNDS_KEY])
    go_next(parent.id, fast=True)


def _render_await_result(child: Task) -> str:
    """Render one peer result with its status for the resume context."""
    marker = await_marker(child) or {}
    who = str(marker.get("peer_display") or child.label)
    if child.status == TaskStatus.ERROR:
        return f"### {who}\n⚠️ {(child.feedback or _message(child, 'no_response')).strip()}"
    return f"### {who}\n{(child.feedback or _message(child, 'empty_response')).strip()}"


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler timeout and fan-in backstops
# ─────────────────────────────────────────────────────────────────────────────

async def resume_expired_awaits() -> None:
    """Fail expired open awaits and resume their parents.

    The generous deadline allows long peer plans while preventing permanent suspension.
    """
    now = datetime.now(timezone.utc)
    expired_parents: set[UUID] = set()
    for task in await _open_await_children():
        marker = await_marker(task) or {}
        deadline_raw = str(marker.get("deadline") or "")
        if not deadline_raw:
            continue
        try:
            deadline = datetime.fromisoformat(deadline_raw)
        except ValueError:
            deadline = now
        if deadline > now:
            continue
        peer = str(
            marker.get("peer_display")
            or marker.get("peer_user_id")
            or _message(task, "peer")
        )
        from app.task.workflow import TaskEvent, transition

        transition(task, TaskEvent.COORDINATION_FAILED)
        if marker.get("kind") == "process":
            task.feedback = render_prompt(
                t("process.await_timeout", _task_language(task)),
                label=marker.get("process_label") or peer,
                run_id=marker.get("run_id") or "?",
            )
        else:
            task.feedback = _message(task, "timeout", peer=peer)
        # Retain the expiration timestamp so a late answer can be relayed during the grace window.
        task.data = {**_data(task), TIMED_OUT_KEY: now.isoformat()}
        task_service.clear_pauses(task)  # Preserve timeout data while clearing pause reasons.
        await task_service.save(task)
        logger.info("ask_agent: await {} expired without a peer answer", task.id)
        if task.parent_id is not None:
            expired_parents.add(task.parent_id)

    for parent_id in expired_parents:
        await maybe_fan_in(parent_id)


async def resume_completed_await_parents() -> None:
    """Retry fan-in for suspended parents after concurrent completion races.

    Scanning suspended tasks without plans is safe because ``maybe_fan_in`` is idempotent and
    ignores tasks without fresh awaits or with a human hold.
    """
    db = get_db()
    query = select(Task.id).where(
        Task.paused.is_(True),
        Task.plan.is_(None),
        Task.status == TaskStatus.DISPATCH,
    )
    rows = (await db.execute(Task.histo_filter(query))).all()
    for (parent_id,) in rows:
        await maybe_fan_in(parent_id)


async def _open_await_children() -> list[Task]:
    """Return open suspended await children among live tasks."""
    db = get_db()
    query = select(Task).where(
        Task.paused.is_(True),
        Task.plan.is_(None),
        Task.parent_id.is_not(None),
    )
    rows: Sequence[Task] = (await db.execute(Task.histo_filter(query))).scalars().all()
    return [t for t in rows if await_marker(t) is not None]
