"""Durable human-referrer questions, reminders, and Goal auto-pause handling."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any
from uuid import UUID

from loguru import logger
from sqlalchemy import Select, String, cast, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql.elements import ColumnElement

from app.messenger import ChoiceRequest, create_choice, register_choice_handler
from app.messenger.models import Interaction
from app.task import TaskCreate, collab, task_service
from app.task.models import Task, TaskStatus
from core.database import get_db
from core.i18n import default_language, is_supported, render_prompt, t

from .models import Goal, GoalCycle, GoalCycleStatus, GoalReferrerType, GoalStatus
from . import calendar as goal_calendar

if TYPE_CHECKING:
    from app.messenger.interactions import ChoiceResolution, PendingChoice


REFERRER_INTERACTION_KIND = "goal_referrer_question"
REFERRER_WAIT_KIND = "goal_referrer"
REFERRER_NO_RESPONSE_PAUSE_REASON = "REFERRER_NO_RESPONSE"
REFERRER_REPLY_INTERVAL_SECONDS = 24 * 60 * 60

_INTERACTION_TIMEOUT_SECONDS = 10 * 365 * 24 * 60 * 60
_REMINDER_SEND_RETRY_SECONDS = 5 * 60
_MAX_QUESTION_CHARS = 8_000
RECOVERY_CYCLE_KEY = "recovery_cycle_id"
_RECOVERY_FEEDBACK_ATTEMPT_KEY = "recovery_feedback_attempted_cycle_id"


def _failed_cycle_answers() -> Select[tuple[Interaction]]:
    """Find captured answers still needed after failure, scoped to the current referrer."""

    recovery_cycle = aliased(GoalCycle)
    recovery_task = aliased(Task)
    recovery_id = Interaction.metadata_[RECOVERY_CYCLE_KEY].as_string()
    # A successful recovery Task may have been purged since its cycle finished.
    applied = (
        select(recovery_cycle.id)
        .outerjoin(recovery_task, recovery_task.id == recovery_cycle.task_id)
        .where(
            recovery_cycle.goal_id == Goal.id,
            cast(recovery_cycle.id, String) == recovery_id,
            or_(recovery_task.status == TaskStatus.SUCCESS, recovery_cycle.task_id.is_(None)),
        )
        .correlate(Goal, Interaction)
        .exists()
    )
    return (
        select(Interaction)
        .join(GoalCycle, cast(GoalCycle.task_id, String) == Interaction.metadata_["task_id"].as_string())
        .join(Task, Task.id == GoalCycle.task_id)
        .where(
            GoalCycle.goal_id == Goal.id,
            Goal.referrer_type == GoalReferrerType.MESSENGER,
            Interaction.kind == REFERRER_INTERACTION_KIND,
            Interaction.status == "RESOLVED",
            Interaction.agent_id == Goal.agent_id,
            Interaction.connection_id == Goal.referrer_connection_id,
            Interaction.user_id == Goal.referrer_user_id,
            Interaction.metadata_["goal_id"].as_string() == cast(Goal.id, String),
            Interaction.resolution["text"].as_string().is_not(None),
            Task.status == TaskStatus.ERROR,
            Task.lease_token.is_(None),
            Task.deleted_at.is_(None),
            ~applied,
        )
        .correlate(Goal)
    )


def pending_cycle_recovery() -> ColumnElement[bool]:
    return _failed_cycle_answers().where(
        Interaction.metadata_[RECOVERY_CYCLE_KEY].as_string().is_(None)
    ).exists()


async def failed_cycle_answers(goal_id: UUID) -> list[Interaction]:
    return list((await get_db().scalars(
        _failed_cycle_answers().where(Goal.id == goal_id)
        .order_by(Interaction.resolved_at, Interaction.id)
    )).all())


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


async def _send_feedback(goal: Goal, interaction: PendingChoice | Interaction, key: str) -> None:
    if (
        goal.referrer_type != GoalReferrerType.MESSENGER
        or interaction.agent_id != goal.agent_id
        or interaction.connection_id is None
        or interaction.connection_id != goal.referrer_connection_id
        or interaction.user_id != goal.referrer_user_id
        or not interaction.room_id
    ):
        return
    from app.messenger import service as messenger_service

    metadata = interaction.metadata_ if isinstance(interaction, Interaction) else interaction.metadata
    language = str(metadata.get("language") or "")
    if not is_supported(language):
        language = default_language()
    try:
        messenger = await messenger_service.messenger_for_agent_connection(
            goal.agent_id, interaction.connection_id
        )
        await messenger.send_to_room(interaction.room_id, _message(
            language, key, goal=goal.title, reference=interaction.reference, goal_id=goal.id,
        ))
    except Exception:
        logger.exception("Could not send Goal feedback for referrer interaction {}", interaction.id)


def _outcome_feedback_key(goal: Goal, task: Task) -> str:
    if goal.status == GoalStatus.COMPLETED:
        return "answer_completed"
    if task.status == TaskStatus.ERROR:
        return "answer_cycle_error"
    if goal.status == GoalStatus.PAUSED:
        return "answer_paused"
    return "answer_processed"


async def notify_cycle_answer_outcome(goal: Goal, task: Task) -> None:
    """Report the outcome of a cycle that resumed normally after the answer."""
    if goal.referrer_type != GoalReferrerType.MESSENGER or task.status != TaskStatus.SUCCESS:
        return
    # Fan-in can finish before Messenger closes the interaction, especially
    # when the model completes immediately after receiving the answer.
    folded_answer = select(Task.id).where(
        Task.parent_id == task.id,
        cast(Task.id, String) == Interaction.metadata_["await_task_id"].as_string(),
        Task.data[collab.FANNED_IN_KEY].as_boolean().is_(True),
    ).correlate(Interaction).exists()
    records = (await get_db().scalars(select(Interaction).where(
        Interaction.kind == REFERRER_INTERACTION_KIND,
        Interaction.status.in_(("PROCESSING", "RESOLVED")),
        Interaction.agent_id == goal.agent_id,
        Interaction.connection_id == goal.referrer_connection_id,
        Interaction.user_id == goal.referrer_user_id,
        Interaction.metadata_["goal_id"].as_string() == str(goal.id),
        folded_answer,
    ))).all()
    for record in records:
        await _send_feedback(goal, record, _outcome_feedback_key(goal, task))


async def process_recovered_cycle_feedback() -> bool:
    """Report one finished recovery, including after a restart between judgement and delivery."""
    db = get_db()
    cycle_id = Interaction.metadata_[RECOVERY_CYCLE_KEY].as_string()
    attempted_id = Interaction.metadata_[_RECOVERY_FEEDBACK_ATTEMPT_KEY].as_string()
    row = (await db.execute(
        select(Interaction, Goal, GoalCycle, Task)
        .join(GoalCycle, cast(GoalCycle.id, String) == cycle_id)
        .join(Goal, Goal.id == GoalCycle.goal_id)
        .join(Task, Task.id == GoalCycle.task_id)
        .where(
            Interaction.kind == REFERRER_INTERACTION_KIND,
            Interaction.status == "RESOLVED",
            Interaction.agent_id == Goal.agent_id,
            Interaction.connection_id == Goal.referrer_connection_id,
            Interaction.user_id == Goal.referrer_user_id,
            Goal.referrer_type == GoalReferrerType.MESSENGER,
            Goal.deleted_at.is_(None),
            GoalCycle.status == GoalCycleStatus.DECIDED,
            cycle_id.is_distinct_from(attempted_id),
        )
        .order_by(GoalCycle.judge_finished_at, Interaction.id)
        .with_for_update(of=Interaction, skip_locked=True)
        .execution_options(populate_existing=True)
        .limit(1)
    )).one_or_none()
    if row is None:
        return False
    interaction, goal, cycle, task = row
    interaction.metadata_ = {
        **interaction.metadata_, _RECOVERY_FEEDBACK_ATTEMPT_KEY: str(cycle.id),
    }
    # A transport without an idempotency key cannot safely replay an uncertain send.
    await db.commit()
    await _send_feedback(goal, interaction, _outcome_feedback_key(goal, task))
    return True


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

    existing = next(
        (wait for wait in await _goal_waits(goal.id)
         if not task_service.has_terminal_outcome(wait)),
        None,
    )
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
    goal: Goal | None = None
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
            await goal_calendar.sync_plan(goal)
            if parent is not None and not task_service.has_terminal_outcome(parent):
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
    if auto_resumed and parent is not None and not task_service.has_terminal_outcome(parent):
        await task_service.save(parent)

    resolved = await collab.resolve_external_await(wait.id, answer)
    if goal_id is not None:
        from . import goal_service

        await goal_service.emit_updated(goal_id)
    if resolved and goal is not None:
        await _send_feedback(goal, interaction, "answer_received")
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
    await goal_calendar.sync_plan(goal, now=now)
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
        select(Task.id, Task.goal_id, next_action_at)
        .join(Goal, Goal.id == Task.goal_id)
        .where(
            Task.paused.is_(True),
            Task.deleted_at.is_(None),
            Task.parent_id.is_not(None),
            Goal.deleted_at.is_(None),
            wait_kind == REFERRER_WAIT_KIND,
            next_action_at.is_not(None),
        )
        .order_by(next_action_at.asc())
        .limit(100)
    )
    candidates = (await get_db().execute(query)).all()
    for wait_id, goal_id, scheduled_at in candidates:
        due_at = _parse_datetime(scheduled_at)
        if due_at is None or due_at > current:
            continue

        # Match answer handling's lock order and leave contended Goals untouched.
        goal = await get_db().scalar(
            select(Goal).where(Goal.id == goal_id, Goal.deleted_at.is_(None))
            .with_for_update(skip_locked=True)
        )
        if goal is None:
            await get_db().rollback()
            continue
        wait = await get_db().scalar(
            select(Task).where(Task.id == wait_id, Task.goal_id == goal.id, Task.paused.is_(True),
                Task.deleted_at.is_(None)).with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        marker = _wait_marker(wait) if wait is not None else None
        due_at = _parse_datetime((marker or {}).get("next_action_at"))
        if wait is None or marker is None or due_at is None or due_at > current:
            await get_db().rollback()
            continue

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

        parent = await task_service.get_by_id(wait.parent_id) if wait.parent_id else None
        parent_can_resume = parent is not None and not task_service.has_terminal_outcome(parent)
        reminders_sent = _integer(marker.get("reminders_sent"))
        if reminders_sent >= goal.referrer_max_reminders:
            if parent_can_resume:
                await _pause_for_no_response(goal, wait, marker, current)
            else:
                # A reminder for a finished cycle must not pause subsequent cycles.
                _set_wait_marker(wait, {**marker, "next_action_at": None})
                await task_service.save(wait)
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
            if parent_can_resume:
                goal.status = GoalStatus.ERROR
                goal.next_cycle_at = None
                goal.last_error = _message(_language(wait), "interaction_unavailable")
                await goal_calendar.sync_plan(goal, now=current)
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
