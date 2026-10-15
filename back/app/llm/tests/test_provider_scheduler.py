"""Admission guarantees shared by all models belonging to one provider."""

import asyncio

import pytest

from app.llm.provider_scheduler import ProviderScheduler, call_priority, default_concurrency


@pytest.mark.asyncio
async def test_priority_cancellation_and_provider_isolation():
    queue = ProviderScheduler()
    active = await queue.acquire(1, 1, 2)
    background = queue.enqueue(1, 1, 2)
    text = queue.enqueue(1, 1, 1)
    voice = queue.enqueue(1, 1, 0)
    independent = await queue.acquire(2, 1, 2)
    assert not any(ticket.future.done() for ticket in (background, text, voice))
    queue.cancel(background)
    active.release()
    spoken = await asyncio.wait_for(asyncio.shield(voice.future), 1)
    assert not text.future.done()
    spoken.release()
    written = await asyncio.wait_for(asyncio.shield(text.future), 1)
    assert background.future.cancelled()
    written.release()
    independent.release()


@pytest.mark.asyncio
async def test_protected_voice_and_text_capacity_and_live_limit_changes():
    queue = ProviderScheduler()
    background = [await queue.acquire(1, 4, 2) for _ in range(2)]
    waiting = queue.enqueue(1, 4, 2)
    voice = await queue.acquire(1, 4, 0)
    text = await queue.acquire(1, 4, 1)
    assert not waiting.future.done()
    queue.configure(1, 1)
    assert not voice.released and not text.released
    for permit in background:
        permit.release()
    voice.release()
    await asyncio.sleep(0)
    assert not waiting.future.done()  # Existing calls drain after a decrease.
    text.release()
    final = await asyncio.wait_for(asyncio.shield(waiting.future), 1)
    final.release()
    queue.configure(1, 0)
    unlimited = await asyncio.gather(*(queue.acquire(1, 0, 2) for _ in range(40)))
    assert all(not permit.released for permit in unlimited)
    for permit in unlimited:
        permit.release()


@pytest.mark.asyncio
async def test_cancelling_an_acquisition_does_not_leak_a_place():
    queue = ProviderScheduler()
    first = await queue.acquire(1, 1, 2)
    waiting = asyncio.create_task(queue.acquire(1, 1, 2))
    await asyncio.sleep(0)
    # Exercise the race between grant and cancellation, not just a queued cancel.
    first.release()
    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting
    replacement = await asyncio.wait_for(queue.acquire(1, 1, 2), 1)
    replacement.release()
    replacement.release()


@pytest.mark.asyncio
async def test_old_requests_progress_and_conversations_share_capacity():
    queue = ProviderScheduler()
    active = await queue.acquire(1, 1, 2)
    old = queue.enqueue(1, 1, 2)
    old.queued_at -= 61
    voice = queue.enqueue(1, 1, 0)
    active.release()
    permit = await asyncio.wait_for(asyncio.shield(old.future), 1)
    assert not voice.future.done()
    permit.release()
    (await voice.future).release()


@pytest.mark.asyncio
async def test_equal_priority_owners_share_capacity_and_keep_fifo_within_each_owner():
    queue = ProviderScheduler()
    active = await queue.acquire(1, 4, 2, owner="first")
    first = queue.enqueue(1, 4, 2, owner="first")
    second = queue.enqueue(1, 4, 2, owner="second")
    await asyncio.sleep(0)
    assert second.future.done() and not first.future.done()
    second.future.result().release()
    active.release()
    (await first.future).release()

    order = []
    tickets = [queue.enqueue(2, 0, 2, owner=owner) for owner in ("a", "a", "a", "b", "b")]
    for index, ticket in enumerate(tickets):
        ticket.future.add_done_callback(lambda _future, index=index: order.append(index))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert order == [0, 3, 1, 4, 2]
    for ticket in tickets:
        ticket.future.result().release()


def test_defaults_and_audio_files_do_not_receive_voice_priority():
    assert default_concurrency("openai_compatible", "openrouter") == 10
    assert default_concurrency("ollama", None) == 1
    assert default_concurrency("openai_compatible", None) == 1
    assert call_priority("audio.transcription") == 2
    assert call_priority("conversation.task_objective", round_origin="voice") == 0
    assert call_priority("conversation.text", round_origin="text") == 1


@pytest.mark.asyncio
async def test_inference_cleanup_releases_later_physical_call_reservations():
    from uuid import uuid4
    from app.llm import provider_scheduler

    queue = provider_scheduler.get_scheduler()
    initial = await queue.acquire(10001, 1, 2)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        with provider_scheduler.reserved(initial):
            first = await provider_scheduler.acquire_call(10001, 1, 2, owner=None)
            provider_scheduler.bind_call(uuid4(), first)
            first.release()
            later = await provider_scheduler.acquire_call(10001, 1, 2, owner=None)
            provider_scheduler.bind_call(uuid4(), later)
            # A failure before the gateway's finalizer must not strand a retry's
            # reservation when the first request's permit was already released.
            raise RuntimeError("synthetic failure before transport setup")
    replacement = await asyncio.wait_for(queue.acquire(10001, 1, 2), 1)
    replacement.release()
