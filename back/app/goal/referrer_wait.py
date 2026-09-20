"""Durable human-referrer questions, reminders, and Goal auto-pause handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select

from app.messenger import ChoiceRequest, create_choice, register_choice_handler
from app.messenger.models import Interaction
from app.task import TaskCreate, collab, task_service
from app.task.models import Task, TaskStatus
from core.database import get_db
from core.i18n import default_language, is_supported, render_prompt, t

from .models import Goal, GoalReferrerType, GoalStatus

if TYPE_CHECKING:
    from app.messenger.interactions import ChoiceResolution, PendingChoice


REFERRER_INTERACTION_KIND = "goal_referrer_question"
REFERRER_WAIT_KIND = "goal_referrer"
REFERRER_NO_RESPONSE_PAUSE_REASON = "REFERRER_NO_RESPONSE"
REFERRER_REPLY_INTERVAL_SECONDS = 24 * 60 * 60

_INTERACTION_TIMEOUT_SECONDS = 10 * 365 * 24 * 60 * 60
_REMINDER_SEND_RETRY_SECONDS = 5 * 60
_MAX_QUESTION_CHARS = 8_000


def _task_data(task: Task) -> dict[str, Any]:
    return task.data if isinstance(task.data, dict) else {}


def _wait_marker(task: Task) -> dict[str, Any] | None:
    marker = collab.await_marker(task)
    if marker is None or marker.get("kind") != REFERRER_WAIT_KIND:
        return None
    return marker


def _set_wait_marker(task: Task, marker: dict[str, Any]) -> None:
    task.data = {**_task_data(task), collab.AWAIT_KEY: marker}


def _language(task: Task) -> str:
    raw = str(_task_data(task).get("language") or "").strip().lower()
    return raw if is_supported(raw) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"goal_referrer.{key}", language), **values)


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


async def _goal_waits(goal_id: UUID) -> list[Task]:
    query = (
        select(Task)
        .where(
            Task.goal_id == goal_id,
            Task.parent_id.is_not(None),
        )
        .order_by(Task.created_at.desc())
        .limit(50)
    )
    rows = list((await get_db().scalars(Task.histo_filter(query))).all())
    return [
        task
        for task in rows
        if _wait_marker(task) is not None
        and not bool(_task_data(task).get(collab.FANNED_IN_KEY))
    ]


async def _current_goal_wait(goal_id: UUID) -> Task | None:
    waits = await _goal_waits(goal_id)
    return waits[0] if waits else None


async def _interaction_for_wait(
    wait: Task, marker: dict[str, Any]
) -> Interaction | None:
    raw_id = marker.get("interaction_id")
    if raw_id:
        try:
            interaction = await get_db().get(Interaction, UUID(str(raw_id)))
        except (TypeError, ValueError):
            interaction = None
        if interaction is not None:
            return interaction

    records = list(
        (
            await get_db().scalars(
                select(Interaction)
                .where(Interaction.kind == REFERRER_INTERACTION_KIND)
                .order_by(Interaction.created_at.desc())
                .limit(100)
            )
        ).all()
    )
    return next(
        (
            record
            for record in records
            if str((record.metadata_ or {}).get("await_task_id") or "") == str(wait.id)
        ),
        None,
    )


def _expire_interaction(interaction: Interaction | None) -> None:
    if interaction is not None and interaction.status in {"PENDING", "PROCESSING"}:
        interaction.status = "EXPIRED"
        interaction.processing_token = None
        interaction.processing_expires_at = None
        interaction.resolved_at = datetime.now(timezone.utc)


def register_referrer_interaction_handler() -> None:
    """Register the durable answer handler idempotently, including after a restart."""

    register_choice_handler(REFERRER_INTERACTION_KIND, _handle_referrer_answer)


async def ask_human_referrer(
    *,
    task_id: UUID,
    agent_id: int,
    question: str,
    language: str,
) -> str:
    """Send one correlated question and create an awaited child below the current Goal Task."""

    clean_question = question.strip()
    if not clean_question:
        raise ValueError(_message(language, "question_required"))
    if len(clean_question) > _MAX_QUESTION_CHARS:
        raise ValueError(
            _message(language, "question_too_long", maximum=_MAX_QUESTION_CHARS)
        )

    parent = await task_service.get_by_id(task_id)
    if parent is None or parent.goal_id is None:
        raise ValueError(_message(language, "goal_task_required"))
    if parent.agent_id != agent_id or parent.status in (TaskStatus.SUCCESS, TaskStatus.ERROR):
        raise ValueError(_message(language, "goal_task_required"))

    from . import goal_service

    goal = await goal_service.get_by_id(parent.goal_id)
    if goal is None or goal.agent_id != agent_id:
        raise ValueError(_message(language, "goal_task_required"))
    if goal.status != GoalStatus.ACTIVE:
        raise ValueError(_message(language, "goal_not_active"))
    if (
        goal.referrer_type != GoalReferrerType.MESSENGER
        or goal.referrer_connection_id is None
        or not goal.referrer_user_id
    ):
        raise ValueError(_message(language, "human_required"))

    existing = await _current_goal_wait(goal.id)
    if existing is not None:
        marker = _wait_marker(existing) or {}
        return _message(
            language,
            "already_waiting",
            referrer=marker.get("peer_display") or goal.referrer_display_name or "",
        )

    await goal_service.assert_referrer_available(goal)
    from app.messenger import service as messenger_service

    messenger = await messenger_service.messenger_for_agent_connection(
        goal.agent_id, goal.referrer_connection_id
    )
    room = await messenger.ensure_direct_room(goal.referrer_user_id)
    now = datetime.now(timezone.utc)
    peer_display = goal.referrer_display_name or goal.referrer_user_id
    marker: dict[str, Any] = {
        "kind": REFERRER_WAIT_KIND,
        "goal_id": str(goal.id),
        "peer_user_id": goal.referrer_user_id,
        "peer_display": peer_display,
        "connection_id": goal.referrer_connection_id,
        "room_id": str(room.id),
        "reminders_sent": 0,
        "next_action_at": (
            now + timedelta(seconds=REFERRER_REPLY_INTERVAL_SECONDS)
        ).isoformat(),
        "asked_at": now.isoformat(),
    }
    wait = await task_service.create(
        TaskCreate(
            label=_message(language, "wait_label", referrer=peer_display),
            objective=clean_question,
            agent_id=agent_id,
            goal_id=goal.id,
            parent_id=parent.id,
            source_task_id=parent.id,
            status=TaskStatus.DISPATCH,
            paused=True,
            ai=False,
            messenger_connection_id=goal.referrer_connection_id,
            message_platform=goal.referrer_platform,
            message_group_id=str(room.id),
            data={
                "language": language,
                "pause_reasons": [task_service.PAUSE_AWAIT],
                collab.AWAIT_KEY: marker,
            },
        )
    )

    register_referrer_interaction_handler()
    try:
        interaction = await create_choice(
            messenger,
            agent_id=agent_id,
            room_id=str(room.id),
            user_id=goal.referrer_user_id,
            request=ChoiceRequest(
                kind=REFERRER_INTERACTION_KIND,
                title=_message(language, "question_title", goal=goal.title),
                body=clean_question,
                free_text=True,
                metadata={
                    "goal_id": str(goal.id),
                    "task_id": str(parent.id),
                    "await_task_id": str(wait.id),
                },
                timeout_seconds=_INTERACTION_TIMEOUT_SECONDS,
                language=language,
            ),
        )
    except Exception:
        await task_service.delete(wait.id)
        raise

    fresh_wait = await task_service.get_by_id(wait.id)
    if fresh_wait is not None and fresh_wait.status not in (TaskStatus.SUCCESS, TaskStatus.ERROR):
        fresh_marker = _wait_marker(fresh_wait) or marker
        fresh_marker = {
            **fresh_marker,
            "interaction_id": str(interaction.id),
            "interaction_reference": interaction.reference,
        }
        _set_wait_marker(fresh_wait, fresh_marker)
        await task_service.save(fresh_wait)

    logger.info(
        "Goal {} is waiting for human referrer {} (Task {}, await {})",
        goal.id,
        goal.referrer_user_id,
        parent.id,
        wait.id,
    )
    return _message(language, "question_sent", referrer=peer_display)


async def _handle_referrer_answer(
    interaction: "PendingChoice", resolution: "ChoiceResolution"
) -> None:
    """Inject the human answer into the waiting Task and resume its Goal safely."""

    answer = (resolution.text or "").strip()
    raw_wait_id = str(interaction.metadata.get("await_task_id") or "")
    if not answer or not raw_wait_id:
        logger.warning("Goal referrer interaction {} has no usable answer", interaction.id)
        return
    try:
        wait_id = UUID(raw_wait_id)
    except ValueError:
        logger.warning("Goal referrer interaction {} has an invalid await id", interaction.id)
        return

    wait = await task_service.get_by_id(wait_id)
    marker = _wait_marker(wait) if wait is not None else None
    if wait is None or marker is None:
        logger.warning("Goal referrer await {} is unavailable", wait_id)
        return

    goal_id = wait.goal_id
    parent = await task_service.get_by_id(wait.parent_id) if wait.parent_id else None
    auto_resumed = False
    if goal_id is not None:
        from . import goal_service

        goal = await goal_service.get_by_id(goal_id, for_update=True)
        if (
            goal is not None
            and goal.status == GoalStatus.PAUSED
            and goal.pause_reason == REFERRER_NO_RESPONSE_PAUSE_REASON
            and bool(marker.get("auto_paused"))
        ):
            goal.status = GoalStatus.ACTIVE
            goal.pause_reason = None
            goal.last_error = None
            if parent is not None:
                task_service.release(parent, task_service.PAUSE_USER)
            auto_resumed = True

    _set_wait_marker(
        wait,
        {
            **marker,
            "answered_at": datetime.now(timezone.utc).isoformat(),
            "next_action_at": None,
        },
    )
    await task_service.save(wait)
    if auto_resumed and parent is not None:
        await task_service.save(parent)

    await collab.resolve_external_await(wait.id, answer)
    if goal_id is not None:
        from . import goal_service

        await goal_service.emit_updated(goal_id)
    logger.info("Goal referrer await {} resolved by human answer", wait.id)


async def _pause_for_no_response(
    goal: Goal,
    wait: Task,
    marker: dict[str, Any],
    now: datetime,
) -> None:
    reminders_sent = _integer(marker.get("reminders_sent"))
    marker = {
        **marker,
        "next_action_at": None,
        "exhausted": True,
        "auto_paused": True,
        "auto_paused_at": now.isoformat(),
    }
    _set_wait_marker(wait, marker)
    goal.status = GoalStatus.PAUSED
    goal.pause_reason = REFERRER_NO_RESPONSE_PAUSE_REASON
    goal.next_cycle_at = None
    parent = await task_service.get_by_id(wait.parent_id) if wait.parent_id else None
    if parent is not None:
        task_service.suspend(parent, task_service.PAUSE_USER)

    await task_service.save(wait)
    if parent is not None:
        await task_service.save(parent)
    from . import goal_service

    await goal_service.emit_updated(goal.id)
    logger.info(
        "Goal {} auto-paused after {} unanswered human-referrer reminder(s)",
        goal.id,
        reminders_sent,
    )


async def process_due_referrer_wait(now: datetime | None = None) -> bool:
    """Send one due reminder or auto-pause one unanswered Goal."""

    register_referrer_interaction_handler()
    current = now or datetime.now(timezone.utc)
    wait_kind = Task.data[collab.AWAIT_KEY]["kind"].as_string()
    next_action_at = Task.data[collab.AWAIT_KEY]["next_action_at"].as_string()
    query = (
        select(Task)
        .where(
            Task.paused.is_(True),
            Task.goal_id.is_not(None),
            Task.parent_id.is_not(None),
            wait_kind == REFERRER_WAIT_KIND,
            next_action_at.is_not(None),
        )
        .order_by(next_action_at.asc())
        .limit(100)
    )
    candidates = list((await get_db().scalars(Task.histo_filter(query))).all())
    for candidate in candidates:
        marker = _wait_marker(candidate)
        due_at = _parse_datetime((marker or {}).get("next_action_at"))
        if marker is None or due_at is None or due_at > current:
            continue

        wait = await get_db().scalar(
            select(Task).where(Task.id == candidate.id).with_for_update(skip_locked=True)
        )
        marker = _wait_marker(wait) if wait is not None else None
        due_at = _parse_datetime((marker or {}).get("next_action_at"))
        if wait is None or marker is None or due_at is None or due_at > current:
            await get_db().rollback()
            continue

        goal = await get_db().scalar(
            select(Goal).where(Goal.id == wait.goal_id).with_for_update(skip_locked=True)
        )
        if goal is None:
            marker["next_action_at"] = None
            marker["error"] = "Goal unavailable"
            _set_wait_marker(wait, marker)
            await task_service.save(wait)
            return True

        if goal.status != GoalStatus.ACTIVE:
            marker = {
                **marker,
                "next_action_at": None,
                "suspended_by_goal": True,
                "remaining_delay_seconds": max(
                    0, int((due_at - current).total_seconds())
                ),
            }
            _set_wait_marker(wait, marker)
            await task_service.save(wait)
            return True

        from . import settings_service

        if not settings_service.is_goal_processing_allowed(goal, now=current):
            await get_db().rollback()
            continue

        reminders_sent = _integer(marker.get("reminders_sent"))
        if reminders_sent >= goal.referrer_max_reminders:
            await _pause_for_no_response(goal, wait, marker, current)
            return True

        interaction = await _interaction_for_wait(wait, marker)
        if interaction is not None and interaction.status == "PROCESSING":
            marker = {
                **marker,
                "next_action_at": (
                    current + timedelta(seconds=_REMINDER_SEND_RETRY_SECONDS)
                ).isoformat(),
            }
            _set_wait_marker(wait, marker)
            await task_service.save(wait)
            return True

        if interaction is None or interaction.status != "PENDING":
            marker = {
                **marker,
                "next_action_at": None,
                "error": "Pending Messenger interaction unavailable",
            }
            _set_wait_marker(wait, marker)
            goal.status = GoalStatus.ERROR
            goal.next_cycle_at = None
            goal.last_error = _message(_language(wait), "interaction_unavailable")
            await task_service.save(wait)
            from . import goal_service

            await goal_service.emit_updated(goal.id)
            return True

        try:
            connection_id = _integer(marker.get("connection_id"), -1)
            room_id = str(marker.get("room_id") or "")
            if connection_id <= 0 or not room_id:
                raise ValueError("Messenger target unavailable")
            from app.messenger import service as messenger_service

            messenger = await messenger_service.messenger_for_agent_connection(
                goal.agent_id, connection_id
            )
            reminder_number = reminders_sent + 1
            await messenger.send_to_room(
                room_id,
                _message(
                    _language(wait),
                    "reminder",
                    number=reminder_number,
                    maximum=goal.referrer_max_reminders,
                    goal=goal.title,
                    question=wait.objective or "",
                    reference=interaction.reference,
                ),
            )
        except Exception as exc:
            marker = {
                **marker,
                "next_action_at": (
                    current + timedelta(seconds=_REMINDER_SEND_RETRY_SECONDS)
                ).isoformat(),
                "send_failures": _integer(marker.get("send_failures")) + 1,
            }
            _set_wait_marker(wait, marker)
            await task_service.save(wait)
            logger.exception("Goal {} referrer reminder failed: {}", goal.id, exc)
            return True

        marker = {
            **marker,
            "reminders_sent": reminder_number,
            "last_reminder_at": current.isoformat(),
            "next_action_at": (
                current + timedelta(seconds=REFERRER_REPLY_INTERVAL_SECONDS)
            ).isoformat(),
            "send_failures": 0,
        }
        _set_wait_marker(wait, marker)
        await task_service.save(wait)
        logger.info(
            "Goal {} sent human-referrer reminder {}/{}",
            goal.id,
            reminder_number,
            goal.referrer_max_reminders,
        )
        return True
    return False


async def resume_wait_for_goal(goal: Goal) -> bool:
    """Resume or rearm an auto-paused human wait after an explicit Goal resume."""

    wait = await _current_goal_wait(goal.id)
    if wait is None:
        return False
    marker = _wait_marker(wait)
    if marker is None:
        return False
    parent = await task_service.get_by_id(wait.parent_id) if wait.parent_id else None
    if parent is not None:
        task_service.release(parent, task_service.PAUSE_USER)

    if wait.status in (TaskStatus.SUCCESS, TaskStatus.ERROR):
        if parent is not None:
            await task_service.save(parent)
            await collab.maybe_fan_in(parent.id)
        return True

    reminders_sent = _integer(marker.get("reminders_sent"))
    if bool(marker.get("exhausted")) and reminders_sent < goal.referrer_max_reminders:
        marker = {
            **marker,
            "exhausted": False,
            "auto_paused": False,
            "next_action_at": datetime.now(timezone.utc).isoformat(),
        }
        _set_wait_marker(wait, marker)
        await task_service.save(wait)
        if parent is not None:
            await task_service.save(parent)
        return True

    if bool(marker.get("exhausted")):
        interaction = await _interaction_for_wait(wait, marker)
        _expire_interaction(interaction)
        _set_wait_marker(
            wait,
            {
                **marker,
                "auto_paused": False,
                "resumed_without_answer_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        await task_service.save(wait)
        if parent is not None:
            await task_service.save(parent)
        return await collab.resolve_external_await(
            wait.id,
            _message(
                _language(wait),
                "resume_without_answer",
                count=reminders_sent,
            ),
            failed=True,
        )

    if bool(marker.get("suspended_by_goal")):
        delay = max(0, _integer(marker.get("remaining_delay_seconds")))
        marker = {
            **marker,
            "suspended_by_goal": False,
            "next_action_at": (
                datetime.now(timezone.utc) + timedelta(seconds=delay)
            ).isoformat(),
        }
        _set_wait_marker(wait, marker)
        await task_service.save(wait)
    if parent is not None:
        await task_service.save(parent)
    return True
