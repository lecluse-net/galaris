"""Admission guarantees shared by all models belonging to one provider."""

import asyncio

import pytest

from app.llm.admission import AdmissionClass, AdmissionSource, admission_context
from app.llm.provider_scheduler import ProviderScheduler, default_concurrency


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
    assert admission_context("audio.transcription").priority == AdmissionClass.BACKGROUND
    assert admission_context("audio.transcription", voice_dialogue=True).priority == AdmissionClass.VOICE
    assert admission_context("conversation.text").priority == AdmissionClass.TEXT


@pytest.mark.parametrize("voice", [False, True])
def test_task_ancestry_never_promotes_work_to_dialogue_capacity(voice):
    from uuid import uuid4

    task, round_, run = uuid4(), uuid4(), uuid4()
    direct = admission_context(
        "agent.dispatch", conversation_round_id=round_, agent_run_id=run, round_is_voice=voice,
    )
    assert direct.source == (AdmissionSource.VOICE_DIALOGUE if voice else AdmissionSource.TEXT_DIALOGUE)
    assert direct.priority == (AdmissionClass.VOICE if voice else AdmissionClass.TEXT)
    assert direct.owner == str(round_)
    derived = admission_context(
        "agent.dispatch", task_id=task, conversation_round_id=round_, agent_run_id=run,
        round_is_voice=voice,
    )
    assert derived.source == AdmissionSource.TASK
    assert derived.priority == AdmissionClass.BACKGROUND
    assert derived.owner == str(task)


@pytest.mark.parametrize("purpose", [None, "audio.transcription", "multimedia.video_generate", "external.operation"])
def test_detached_work_keeps_run_ownership_without_dialogue_priority(purpose):
    from uuid import uuid4

    run = uuid4()
    context = admission_context(purpose, agent_run_id=run)
    assert context.source == AdmissionSource.BACKGROUND
    assert context.priority == AdmissionClass.BACKGROUND
    assert context.owner == str(run)


def test_background_work_uses_distinct_owners_without_promoting_its_origin():
    from uuid import uuid4

    from app.llm.subscription_policy import LLMExecutionAuthority

    key = uuid4()
    identities = [
        {"process_run_id": key},
        {"media_generation_id": key},
        {"authority": LLMExecutionAuthority(source_kind="conversation_round", source_id=str(key))},
        {"agent_id": 7},
        {"requester_user_id": 7},
    ]
    contexts = [admission_context("external.operation", **identity) for identity in identities]
    assert all(context.priority == AdmissionClass.BACKGROUND for context in contexts)
    assert all(context.owner is not None for context in contexts)
    assert len({context.owner for context in contexts}) == len(contexts)
    task = admission_context("agent.exec", task_id=key, **identities[2])
    assert task.owner == str(key) and task.source == AdmissionSource.TASK
    run = admission_context("external.operation", agent_run_id=key, **identities[0])
    assert run.owner == str(key)


def test_incomplete_background_provenance_stays_anonymous_and_source_keys_are_unambiguous():
    from app.llm.subscription_policy import LLMExecutionAuthority

    assert admission_context(None, authority=LLMExecutionAuthority(source_kind="lab_run")).owner is None
    first, second = [admission_context(None, authority=LLMExecutionAuthority(source_kind=kind, source_id=key))
                     for kind, key in [("a:b", "c"), ("a", "b:c")]]
    assert first.owner != second.owner


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
