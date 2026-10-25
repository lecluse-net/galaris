"""Exercise actual transport tracks against a deterministic media clock."""

import asyncio
import inspect
from collections.abc import Callable

import pytest

from app.chat.webrtc import _OutgoingAudioTrack
from app.voice import AudioFrame, audio
from bridge.matrix.call import _OutboundAudioTrack
from bridge.nextcloud.call import _build_out_track


@pytest.fixture(params=["browser", "matrix", "nextcloud"])
def output(request):
    track = {
        "browser": _OutgoingAudioTrack,
        "matrix": _OutboundAudioTrack,
        "nextcloud": _build_out_track,
    }[request.param]()

    async def push(pcm):
        result = track.push(AudioFrame(pcm=pcm) if request.param == "browser" else pcm)
        if inspect.isawaitable(result):
            await result

    yield track, push
    track.stop()


class _Clock:
    now = 0.0
    overshoot = 0.0
    on_sleep: Callable[[], object] | None = None

    async def sleep(self, delay):
        self.now += max(0, delay) + self.overshoot
        if self.on_sleep is not None:
            self.on_sleep()


@pytest.fixture
def clock(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(asyncio, "sleep", clock.sleep)
    monkeypatch.setattr(audio, "monotonic", lambda: clock.now, raising=False)
    return clock


@pytest.mark.asyncio
@pytest.mark.parametrize("overshoot", [0.0, 0.003])
async def test_transport_keeps_audio_cadence_despite_encoding_cost(output, clock, overshoot):
    track, push = output
    clock.overshoot = overshoot
    pcm = b"\x01\x00" * 960
    for index in range(500):
        await push(pcm)
        frame = await track.recv()
        assert frame.pts == index * 960
        assert bytes(frame.planes[0])[:len(pcm)] == pcm
        if index != 499:
            clock.now += 0.005  # RTP encoding and transmission outside recv().

    # Ten seconds of audio must not accumulate 500 encoding/scheduler delays.
    assert clock.now == pytest.approx(10.0 + overshoot)


@pytest.mark.asyncio
async def test_transport_resumes_after_stall_without_a_catchup_burst(output, clock):
    track, _ = output
    await track.recv()
    clock.now += 2.0
    await track.recv()
    resumed = clock.now
    for _ in range(5):
        await track.recv()
    assert clock.now - resumed == pytest.approx(0.100)


@pytest.mark.asyncio
async def test_barge_in_during_pacing_does_not_send_cleared_speech(output, clock):
    track, push = output
    await push(b"\x01\x00" * 960)
    clock.on_sleep = track.clear

    frame = await track.recv()

    assert not any(bytes(frame.planes[0]))
    await track.wait_drained()


@pytest.mark.asyncio
async def test_paused_transport_retains_exact_audio_and_resumes_without_repeating(output, clock):
    track, push = output
    first = b"\x01\x00" * 960
    remainder = b"\x02\x00" * 480
    following = b"\x03\x00" * 480
    await push(first + remainder)
    assert bytes((await track.recv()).planes[0])[:len(first)] == first

    # Pause while a frame is being paced, retaining partial frames as well as
    # speech queued/generated after the pause began.
    clock.on_sleep = lambda: track.set_paused(True)
    assert not any(bytes((await track.recv()).planes[0]))
    clock.on_sleep = None
    await push(following)
    assert not any(bytes((await track.recv()).planes[0]))
    drained = asyncio.create_task(track.wait_drained())
    await asyncio.sleep(0)
    assert not drained.done()
    track.set_paused(False)
    resumed = await track.recv()
    assert bytes(resumed.planes[0])[:1920] == remainder + following
    assert resumed.pts == 3 * 960
    await drained
    assert not any(bytes((await track.recv()).planes[0]))


@pytest.mark.asyncio
async def test_confirmed_interruption_discards_paused_audio(output, clock):
    track, push = output
    await push(b"\x01\x00" * 960)
    track.set_paused(True)
    track.clear()
    track.set_paused(False)
    assert not any(bytes((await track.recv()).planes[0]))
    await track.wait_drained()


@pytest.mark.asyncio
async def test_cancelled_send_preserves_unsent_audio(output, clock, monkeypatch):
    track, push = output
    pcm = b"\x01\x00" * 960
    await push(pcm)

    async def cancel(_delay):
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", cancel)
    with pytest.raises(asyncio.CancelledError):
        await track.recv()
    monkeypatch.setattr(asyncio, "sleep", clock.sleep)

    frame = await track.recv()
    assert bytes(frame.planes[0])[:len(pcm)] == pcm
    assert frame.pts == 0
