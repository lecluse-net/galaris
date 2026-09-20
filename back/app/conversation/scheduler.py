"""Independent durable scheduler for short conversation rounds."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import os
import socket
from uuid import UUID, uuid4

from loguru import logger

from app.agent import AIMessage
from core.database import get_db_session
from .contracts import ConversationLeaseLostError


_POLL_SECONDS = 0.5
_MAX_CONCURRENCY = 4
# Reasoning models can spend five minutes before their first tool call. Leave room
# for search results and the final answer while keeping the entire attempt bounded.
_ACTION_TIMEOUT_SECONDS = 900.0
_CANCEL_WAIT_SECONDS = 1.0
_WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
_scheduler_task: asyncio.Task[None] | None = None
_wake_event: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None
_running: dict[UUID, asyncio.Task[None]] = {}

ClaimedRound = tuple[UUID, UUID]


def start() -> None:
    global _scheduler_task, _wake_event, _loop
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _loop = asyncio.get_running_loop()
    _wake_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_run_loop(), name="conversation-scheduler")
    logger.info("Conversation scheduler started")


async def stop() -> None:
    global _scheduler_task, _wake_event, _loop
    root = _scheduler_task
    _scheduler_task = None
    _wake_event = None
    _loop = None
    if root is not None:
        root.cancel()
        await asyncio.gather(root, return_exceptions=True)
    running = tuple(_running.values())
    for task in running:
        task.cancel()
    if running:
        await asyncio.gather(*running, return_exceptions=True)
    _running.clear()
    logger.info("Conversation scheduler stopped")


def is_running() -> bool:
    return _scheduler_task is not None and not _scheduler_task.done()


def wake() -> None:
    loop = _loop
    event = _wake_event
    if loop is None or event is None or loop.is_closed():
        return
    loop.call_soon_threadsafe(event.set)


async def cancel_round(round_id: UUID) -> bool:
    """Cancel a locally running round without making administrative deletion wait forever."""

    worker = _running.get(round_id)
    if worker is None or worker.done():
        return False
    worker.cancel()
    done, _pending = await asyncio.wait({worker}, timeout=_CANCEL_WAIT_SECONDS)
    if worker not in done:
        logger.warning(
            "Conversation worker {} did not stop within {} second(s) after cancellation",
            round_id,
            _CANCEL_WAIT_SECONDS,
        )
    return True


async def _claim() -> ClaimedRound | None:
    from .service import claim_next_round
    from .facade import publish_round_activity

    async with get_db_session():
        round_ = await claim_next_round(_WORKER_ID)
        if round_ is None:
            return None
        if round_.lease_token is None:
            raise RuntimeError(f"Claimed conversation round {round_.id} has no lease token.")
        claimed = (round_.id, round_.lease_token)
    await publish_round_activity(claimed[0])
    return claimed


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


async def _execute_action(round_id: UUID, lease_token: UUID) -> None:
    from . import controller
    from .contracts import (
        ConversationExecutionError,
        ConversationOutcome,
    )
    from .preparation import ConversationSuperseded
    from .facade import publish_round_activity
    from .runtime import ConversationRuntimeStream
    from .service import build_turn, complete_round, fail_round

    completed_successfully = False
    progress: ConversationRuntimeStream | None = None
    terminal_result = None
    try:
        async with get_db_session():
            turn = await build_turn(round_id, lease_token=lease_token)
        progress = ConversationRuntimeStream(
            room_id=turn.room_id, round_id=round_id,
            topic_id=turn.topic_id, attempt=turn.attempt,
        )
        turn = replace(
            turn,
            publish_progress=progress.append,
            reset_progress=progress.reset,
        )
        await progress.start()
        await publish_round_activity(round_id)
        outcome = await controller.run(turn)
        terminal_result = outcome.execution_result
        if terminal_result is None:
            terminal_result = progress.snapshot()
            terminal_result.result = outcome.text
        normalized_result = progress.snapshot(terminal_result)
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
        completed_successfully = status == "SUCCEEDED"
        await publish_round_activity(round_id)
        logger.info("Conversation round {} completed status={}", round_id, status)
    except ConversationSuperseded:
        terminal_result = progress.snapshot() if progress else None
        if terminal_result is not None:
            terminal_result.result = ""
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
            await progress.finish(success=completed_successfully, result=terminal_result)


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


def _done(round_id: UUID, task: asyncio.Task[None]) -> None:
    _running.pop(round_id, None)
    try:
        task.result()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Conversation worker {} terminated unexpectedly", round_id)
    wake()


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

    while True:
        try:
            claimed_any = False
            while len(_running) < _MAX_CONCURRENCY:
                claimed = await _claim()
                if claimed is None:
                    break
                round_id, lease_token = claimed
                claimed_any = True
                worker = asyncio.create_task(
                    _execute(round_id, lease_token),
                    name=f"conversation-round-{round_id}",
                )
                _running[round_id] = worker
                worker.add_done_callback(
                    lambda task, claimed_id=round_id: _done(claimed_id, task)
                )
            while len(_running) < _MAX_CONCURRENCY:
                round_id = await _claim_round_notification()
                if round_id is None:
                    break
                claimed_any = True
                worker = asyncio.create_task(
                    _execute_round_notification(round_id),
                    name=f"conversation-round-notification-{round_id}",
                )
                _running[round_id] = worker
                worker.add_done_callback(
                    lambda task, claimed_id=round_id: _done(claimed_id, task)
                )
            while len(_running) < _MAX_CONCURRENCY:
                link_id = await _claim_task_notification()
                if link_id is None:
                    break
                claimed_any = True
                worker = asyncio.create_task(
                    _execute_task_notification(link_id),
                    name=f"conversation-task-notification-{link_id}",
                )
                _running[link_id] = worker
                worker.add_done_callback(
                    lambda task, claimed_id=link_id: _done(claimed_id, task)
                )
            while len(_running) < _MAX_CONCURRENCY:
                link_id = await _claim_process_notification()
                if link_id is None:
                    break
                claimed_any = True
                worker = asyncio.create_task(
                    _execute_process_notification(link_id),
                    name=f"conversation-process-notification-{link_id}",
                )
                _running[link_id] = worker
                worker.add_done_callback(
                    lambda task, claimed_id=link_id: _done(claimed_id, task)
                )
            if claimed_any:
                await asyncio.sleep(0)
                continue
            event = _wake_event
            if event is None:
                await asyncio.sleep(_POLL_SECONDS)
                continue
            event.clear()
            try:
                await asyncio.wait_for(event.wait(), timeout=_POLL_SECONDS)
            except TimeoutError:
                pass
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Conversation scheduler loop failed")
            await asyncio.sleep(_POLL_SECONDS)


__all__ = ["cancel_round", "is_running", "start", "stop", "wake"]
