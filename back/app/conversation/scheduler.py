"""Independent durable scheduler for short conversation rounds."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from dataclasses import replace
import os
import socket
from uuid import UUID, uuid4

from loguru import logger

from app.agent import AIMessage
from core import settings
from core.database import Base, get_db_session, watch_committed_changes
from core.failure_journal import mark_failure_run_recovered
from .contracts import ConversationLeaseLostError


_POLL_SECONDS = 30.0  # Recovery only; committed changes wake the scheduler immediately.
_ERROR_RETRY_SECONDS = 1.0
# Reasoning models can spend five minutes before their first tool call. Leave room
# for search results and the final answer while keeping the entire attempt bounded.
_ACTION_TIMEOUT_SECONDS = 900.0
_CANCEL_WAIT_SECONDS = 1.0
_SHUTDOWN_DRAIN_SECONDS = 20.0
_shutdown_requested = False
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
_scheduler_task: asyncio.Task[None] | None = None
_wake_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None
_watching_changes = False
_running: dict[asyncio.Task[None], UUID] = {}
# Only round fallback deliveries belong to the round cancellation scope.
_notifications: dict[asyncio.Task[None], UUID | None] = {}
_round_generation = 0
_delivery_generation = 0
_contact_generation = 0

ClaimedRound = tuple[UUID, UUID]


def start() -> None:
    global _scheduler_task, _wake_event, _loop, _watching_changes, _shutdown_requested
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _shutdown_requested = False
    _loop = asyncio.get_running_loop()
    _wake_event = asyncio.Event()
    if not _watching_changes:
        from app.task import Task, TaskStatus
        from app.process import ProcessRun
        from app.messenger import PermissionDecision
        from app.agent import Agent
        from app.connection import Connection
        from .models import ConversationRound, ConversationRoundMessage, ConversationTaskLink, ConversationProcessLink

        watch_committed_changes({
            ConversationRound: ("status", "lease_token"),
            ConversationRoundMessage: (),
        }, wake)
        watch_committed_changes({
            ConversationTaskLink: ("notification_state", "notification_task_attempt_count"),
            ConversationProcessLink: ("notification_state",),
            Task: ("status", "lease_token", "attempt_count", "deleted_at"),
            ProcessRun: ("status",),
            PermissionDecision: ("allowed", "deleted_at", "approver_user_id"),
            Agent: ("user_id",),
            Connection: ("active", "agent_id"),
        }, _signal)

        def delivery_may_be_ready(entity: Base) -> bool:
            # An unloaded field is ambiguous. Wake conservatively without
            # loading an ORM object during the producer's flush.
            if "status" not in vars(entity):
                return True
            if isinstance(entity, ConversationRound):
                return entity.status == "ERROR_RESOLVED"
            if isinstance(entity, Task):
                return entity.status in (TaskStatus.SUCCESS, TaskStatus.ERROR)
            if isinstance(entity, ProcessRun):
                return entity.status in {"success", "error", "cancelled"}
            return True

        watch_committed_changes({
            ConversationRound: ("status", "delivery_state"),
            ConversationTaskLink: ("notification_state", "notification_task_attempt_count"),
            ConversationProcessLink: ("notification_state",),
            Task: ("status", "lease_token", "attempt_count", "deleted_at"),
            ProcessRun: ("status",),
        }, _wake_deliveries, when=delivery_may_be_ready)
        watch_committed_changes(
            {ConversationRound: ("status", "contact_authorization_pending")},
            _wake_contacts, when=lambda entity: vars(entity).get("contact_authorization_pending") is not False,
        )
        _watching_changes = True
    _scheduler_task = asyncio.create_task(_run_loop(), name="conversation-scheduler")
    logger.info("Conversation scheduler started")


async def stop() -> None:
    global _scheduler_task, _wake_event, _loop, _shutdown_requested
    _shutdown_requested = True
    root = _scheduler_task
    _scheduler_task = None
    _wake_event = None
    _loop = None
    if root is not None:
        root.cancel()
        await asyncio.gather(root, return_exceptions=True)
    running = (*_running, *_notifications)
    if running:
        # Preparation/model calls stop promptly. A tool already running may
        # finish and persist its receipt before we cancel the remaining work.
        _done, pending = await asyncio.wait(running, timeout=_SHUTDOWN_DRAIN_SECONDS)
        for task in pending:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)
    _running.clear()
    _notifications.clear()
    logger.info("Conversation scheduler stopped")


def is_running() -> bool:
    return _scheduler_task is not None and not _scheduler_task.done()


def wake() -> None:
    """Recheck durable dialogue admissions after a relevant commit or explicit wake."""
    global _round_generation
    _round_generation += 1
    _signal()


def _signal() -> None:
    loop = _loop
    event = _wake_event
    if loop is None or event is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(event.set)


def _wake_deliveries() -> None:
    global _delivery_generation
    _delivery_generation += 1
    _signal()


def _wake_contacts() -> None:
    global _contact_generation
    _contact_generation += 1
    _signal()


async def cancel_round(round_id: UUID) -> bool:
    """Cancel a locally running round without making administrative deletion wait forever."""

    workers = {
        worker for worker, owner in (*_running.items(), *_notifications.items())
        if owner == round_id and not worker.done()
    }
    if not workers:
        return False
    for worker in workers:
        worker.cancel()
    _, pending = await asyncio.wait(workers, timeout=_CANCEL_WAIT_SECONDS)
    if pending:
        logger.warning(
            "Conversation worker {} did not stop within {} second(s) after cancellation",
            round_id,
            _CANCEL_WAIT_SECONDS,
        )
    return True


async def _claim() -> ClaimedRound | None:
    from .service import claim_next_round

    async with get_db_session():
        round_ = await claim_next_round(_WORKER_ID)
        if round_ is None:
            return None
        if round_.lease_token is None:
            raise RuntimeError(f"Claimed conversation round {round_.id} has no lease token.")
        return round_.id, round_.lease_token


async def _claim_round_notification() -> UUID | None:
    from .service import claim_next_round_notification

    async with get_db_session():
        return await claim_next_round_notification()


async def _claim_process_notification() -> UUID | None:
    from .service import claim_next_process_notification

    async with get_db_session():
        return await claim_next_process_notification()


async def _claim_task_notification() -> UUID | None:
    from .service import claim_next_task_notification

    async with get_db_session():
        return await claim_next_task_notification()


@asynccontextmanager
async def _execution_activity(round_id: UUID) -> AsyncGenerator[asyncio.Event]:
    """Send ordered refresh hints alongside preparation and model execution."""
    from .facade import publish_round_activity

    running = asyncio.Event()

    async def announce() -> None:
        try:
            await publish_round_activity(round_id)
            await running.wait()
            await publish_round_activity(round_id)
        except Exception:
            logger.exception("Conversation execution refresh failed for round {}", round_id)

    publisher = asyncio.create_task(announce(), name=f"conversation-activity-{round_id}")
    try:
        yield running
    finally:
        # The next durable transition publishes its own refresh. An obsolete
        # hint must not outlive this attempt or accumulate behind a slow client.
        publisher.cancel()
        await asyncio.gather(publisher, return_exceptions=True)


async def _execute_action(round_id: UUID, lease_token: UUID) -> None:
    from . import controller
    from .contracts import (
        ConversationExecutionError,
        ConversationOutcome,
    )
    from .preparation import ConversationSuperseded, watch_room_control
    from .facade import publish_round_activity
    from .runtime import ConversationRuntimeStream
    from .service import build_turn, complete_round, fail_round

    completed_successfully = False
    progress: ConversationRuntimeStream | None = None
    terminal_result = None
    try:
        async with _execution_activity(round_id) as running:
            async with get_db_session():
                turn = await build_turn(round_id, lease_token=lease_token, should_suspend=lambda: _shutdown_requested)
            progress = ConversationRuntimeStream(
                room_id=turn.room_id, round_id=round_id,
                topic_id=turn.topic_id, attempt=turn.attempt,
            )
            turn = replace(
                turn,
                publish_progress=progress.append,
                reset_progress=progress.reset,
                should_suspend=lambda: _shutdown_requested,
            )
            await progress.start()
            running.set()
            with watch_room_control(turn.room_id) as wait_for_interrupt:
                outcome = await controller.run(replace(turn, wait_for_interrupt=wait_for_interrupt))
        normalized_result = progress.snapshot(outcome.execution_result)
        if outcome.execution_result is None:
            normalized_result.result = outcome.text
        has_visible_text = any(
            message.type == "text" and message.content.strip()
            for message in normalized_result.messages
        )
        if not has_visible_text and outcome.text.strip():
            normalized_result.messages.append(
                AIMessage(type="text", content=outcome.text.strip())
            )
        terminal_result = normalized_result
        outcome = replace(outcome, execution_result=normalized_result)
        async with get_db_session():
            status = await complete_round(round_id, outcome, lease_token=lease_token)
        if status in {"SUPERSEDED", "STALE_AFTER_EFFECT", "INTERRUPTED"}:
            terminal_result.metadata["interrupted_by_new_input"] = True
        completed_successfully = status == "SUCCEEDED"
        if completed_successfully:
            await mark_failure_run_recovered(round_id)
        await publish_round_activity(round_id)
        logger.info("Conversation round {} completed status={}", round_id, status)
    except ConversationSuperseded:
        terminal_result = progress.snapshot() if progress else None
        if terminal_result is not None:
            terminal_result.result = ""
            terminal_result.metadata["interrupted_by_new_input"] = True
        async with get_db_session():
            await complete_round(round_id, ConversationOutcome(
                text="", execution_result=terminal_result, metadata={"interrupted": True},
            ), lease_token=lease_token)
        await publish_round_activity(round_id)
    except asyncio.CancelledError:
        raise
    except ConversationLeaseLostError:
        raise
    except ConversationExecutionError as exc:
        terminal_result = progress.snapshot(exc.execution_result) if progress else exc.execution_result
        logger.exception("Conversation round {} failed with a partial trace", round_id)
        async with get_db_session():
            await fail_round(
                round_id,
                str(exc),
                lease_token=lease_token,
                execution_result=terminal_result,
            )
        await publish_round_activity(round_id)
    except Exception as exc:
        logger.exception("Conversation round {} failed", round_id)
        terminal_result = progress.snapshot() if progress else None
        async with get_db_session():
            await fail_round(round_id, str(exc), lease_token=lease_token, execution_result=terminal_result)
        await publish_round_activity(round_id)
    finally:
        if progress is not None:
            await progress.finish(success=completed_successfully, result=terminal_result, reconciled=True)


async def _heartbeat_round(round_id: UUID, lease_token: UUID) -> None:
    from .service import LEASE_SECONDS, renew_round_lease, round_attempt_succeeded

    interval = max(5.0, LEASE_SECONDS / 6)
    while True:
        await asyncio.sleep(interval)
        async with get_db_session():
            renewed = await renew_round_lease(round_id, lease_token)
            if not renewed and await round_attempt_succeeded(round_id, lease_token):
                # Completion commits and releases the lease before publishing the
                # outgoing message. Let that publication and the live stream finish.
                return
        if not renewed:
            raise ConversationLeaseLostError(
                f"Conversation round lease lost for {round_id}"
            )


async def _fail_timed_out_round(round_id: UUID, lease_token: UUID) -> None:
    from .facade import publish_round_activity
    from .service import fail_round

    async with get_db_session():
        await fail_round(round_id, "Conversation round execution timed out.", lease_token=lease_token)
    await publish_round_activity(round_id)


async def _execute(round_id: UUID, lease_token: UUID) -> None:
    """Execute one bounded conversation round while owning its durable lease."""

    action = asyncio.create_task(
        _execute_action(round_id, lease_token), name=f"conversation-action-{round_id}"
    )
    heartbeat = asyncio.create_task(
        _heartbeat_round(round_id, lease_token),
        name=f"conversation-lease-heartbeat-{round_id}",
    )
    try:
        async with asyncio.timeout(_ACTION_TIMEOUT_SECONDS):
            done, _pending = await asyncio.wait(
                {action, heartbeat}, return_when=asyncio.FIRST_COMPLETED
            )
            if heartbeat in done:
                await heartbeat
            await action
    except TimeoutError:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        logger.error(
            "Conversation round {} timed out after {} seconds",
            round_id,
            _ACTION_TIMEOUT_SECONDS,
        )
        await _fail_timed_out_round(round_id, lease_token)
    except ConversationLeaseLostError:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        logger.warning("Conversation round {} stopped after lease loss", round_id)
    except asyncio.CancelledError:
        action.cancel()
        await asyncio.gather(action, return_exceptions=True)
        from .service import interrupt_round

        # The cancelled runtime saves its history and tool receipts before its
        # lease is released. Administrative cancellation already revoked it.
        owner = asyncio.current_task()
        async with get_db_session():
            if not _shutdown_requested and owner is not None and not owner.cancelling():
                # A transport/tool can cancel its own action while this worker
                # remains healthy. Bound those faults by the normal retry budget.
                from .service import fail_round

                await fail_round(round_id, "Conversation execution interrupted while the worker was running.",
                    lease_token=lease_token)
            else:
                await interrupt_round(round_id, lease_token=lease_token)
        from .facade import publish_round_activity

        # The release is already durable. A stuck observer must not keep the
        # worker alive after its last opportunity to announce the transition.
        try:
            async with asyncio.timeout(_CANCEL_WAIT_SECONDS):
                await publish_round_activity(round_id)
        except TimeoutError:
            logger.warning("Conversation cancellation refresh timed out for round {}", round_id)
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


async def _execute_round_notification(round_id: UUID) -> None:
    from .service import deliver_round_notification

    try:
        async with get_db_session():
            await deliver_round_notification(round_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Conversation round notification {} has an ambiguous delivery state",
            round_id,
        )


async def _execute_process_notification(link_id: UUID) -> None:
    from .service import deliver_process_notification

    try:
        async with get_db_session():
            await deliver_process_notification(link_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Conversation Process notification {} has an ambiguous delivery state",
            link_id,
        )


async def _execute_task_notification(link_id: UUID) -> None:
    from .service import deliver_task_notification

    try:
        async with get_db_session():
            await deliver_task_notification(link_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception(
            "Conversation Task notification {} has an ambiguous delivery state",
            link_id,
        )


def _done(task: asyncio.Task[None]) -> None:
    _running.pop(task, None)
    _notifications.pop(task, None)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Conversation worker {} terminated unexpectedly", task.get_name())
    _signal()


async def _run_loop() -> None:
    try:
        from .service import reconcile_terminal_round_llm_calls

        async with get_db_session():
            reconciled = await reconcile_terminal_round_llm_calls()
        if reconciled:
            logger.warning(
                "Conversation scheduler reconciled {} orphaned LLM call(s)", reconciled
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Conversation LLM-call startup reconciliation failed")

    deliveries = deque((
        ("round", _claim_round_notification, _execute_round_notification),
        ("task", _claim_task_notification, _execute_task_notification),
        ("process", _claim_process_notification, _execute_process_notification),
    ))
    loop = asyncio.get_running_loop()
    empty_round_generation = empty_delivery_generation = empty_contact_generation = -1
    recovery_at = loop.time() + _POLL_SECONDS
    while True:
        try:
            slots = settings.CONVERSATION_WORKER_CONCURRENCY
            event = _wake_event
            if event is not None:
                event.clear()
            if loop.time() >= recovery_at:
                empty_round_generation = empty_delivery_generation = empty_contact_generation = -1
                recovery_at = loop.time() + _POLL_SECONDS
            if empty_contact_generation != _contact_generation:
                from .contact_authorization import reconcile_contact_authorizations
                contact_generation = _contact_generation
                if not await reconcile_contact_authorizations():
                    empty_contact_generation = contact_generation
            claimed_any = False
            # Keep one place for each kind of work when the other is saturated.
            # Idle capacity is shared, within a total bound of slots + 1.
            while (
                empty_round_generation != _round_generation
                and len(_running) < slots
                and len(_running) + len(_notifications) < slots + 1
            ):
                round_generation = _round_generation
                claimed = await _claim()
                if claimed is None:
                    # A concurrent commit (or a cancellation inside the claim)
                    # can make the next round eligible during this scan.
                    empty_round_generation = round_generation
                    break
                round_id, lease_token = claimed
                claimed_any = True
                worker = asyncio.create_task(
                    _execute(round_id, lease_token),
                    name=f"conversation-round-{round_id}",
                )
                _running[worker] = round_id
                worker.add_done_callback(_done)
            while (
                empty_delivery_generation != _delivery_generation
                and len(_notifications) < slots
                and len(_running) + len(_notifications) < slots + 1
            ):
                delivery_generation = _delivery_generation
                for _ in range(len(deliveries)):
                    kind, claim, deliver = deliveries[0]
                    deliveries.rotate(-1)
                    identifier = await claim()
                    if identifier is not None:
                        worker = asyncio.create_task(
                            deliver(identifier), name=f"conversation-{kind}-notification-{identifier}",
                        )
                        _notifications[worker] = identifier if kind == "round" else None
                        worker.add_done_callback(_done)
                        claimed_any = True
                        break
                else:
                    # Preserve a commit that arrived while the claims were awaiting SQL.
                    empty_delivery_generation = delivery_generation
                    break
            if claimed_any:
                await asyncio.sleep(0)
                continue
            event = _wake_event
            if event is None:
                await asyncio.sleep(_POLL_SECONDS)
                continue
            try:
                await asyncio.wait_for(event.wait(), timeout=max(0.0, recovery_at - loop.time()))
            except TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Conversation scheduler loop failed")
            await asyncio.sleep(_ERROR_RETRY_SECONDS)


__all__ = ["cancel_round", "is_running", "start", "stop", "wake"]
