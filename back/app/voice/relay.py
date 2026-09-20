"""Bidirectional PCM relay between a call transport and PulseAudio."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator

from loguru import logger
from core.i18n import render_prompt, t

from .audio_devices import PulseAudioDevices
from .interface import CallTransport
from .models import AudioFrame


def _error(key: str, **values: Any) -> str:
    return render_prompt(t(f"voice.{key}"), **values)


async def relay_call_audio(
    transport: CallTransport,
    handle: object,
    devices: PulseAudioDevices,
) -> None:
    """Run both audio directions until one side stops or raises."""
    tasks = [
        asyncio.create_task(
            write_frames_to_pulse_source(transport.inbound_audio(handle), devices),
            name="voice_call_to_pulse",
        ),
        asyncio.create_task(
            transport.send_audio(handle, pulse_sink_monitor_frames(devices)),
            name="voice_pulse_to_call",
        ),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            exc = task.exception()
            if exc is not None:
                raise exc
        for task in pending:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def write_frames_to_pulse_source(
    frames: AsyncIterator[AudioFrame],
    devices: PulseAudioDevices,
) -> None:
    """Write call inbound PCM into the virtual microphone sink."""
    proc = await asyncio.create_subprocess_exec(
        "pacat",
        "--raw",
        "--playback",
        "--format=s16le",
        f"--rate={devices.config.sample_rate}",
        f"--channels={devices.config.channels}",
        f"--device={devices.mic_sink_name}",
        stdin=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=devices.env,
    )
    if proc.stdin is None:
        raise RuntimeError(_error("pulse_playback_unavailable"))

    count = 0
    signal = 0
    try:
        async for frame in frames:
            if not frame.pcm:
                continue
            proc.stdin.write(frame.pcm)
            await proc.stdin.drain()
            count += 1
            if any(frame.pcm):
                signal += 1
            if count == 1 or count % 250 == 0:
                logger.info(
                    "Voice PulseAudio: inbound -> microphone frames={} signal_frames={} bytes={}",
                    count,
                    signal,
                    len(frame.pcm),
                )
    except BrokenPipeError:
        logger.info("Voice PulseAudio: PulseAudio closed the microphone pacat process")
    finally:
        proc.stdin.close()
        await _stop_process(proc)


async def pulse_sink_monitor_frames(devices: PulseAudioDevices) -> AsyncIterator[AudioFrame]:
    """Read external-runtime speaker audio from the sink monitor as PCM frames."""
    proc = await asyncio.create_subprocess_exec(
        "parec",
        "--raw",
        "--format=s16le",
        f"--rate={devices.config.sample_rate}",
        f"--channels={devices.config.channels}",
        f"--device={devices.sink_monitor}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=devices.env,
    )
    if proc.stdout is None:
        raise RuntimeError(_error("pulse_capture_unavailable"))

    count = 0
    signal = 0
    try:
        while True:
            try:
                pcm = await proc.stdout.readexactly(devices.config.frame_bytes)
            except asyncio.IncompleteReadError as exc:
                if exc.partial:
                    yield AudioFrame(
                        pcm=exc.partial,
                        sample_rate=devices.config.sample_rate,
                        channels=devices.config.channels,
                    )
                stderr = ""
                if proc.stderr is not None:
                    stderr = (await proc.stderr.read()).decode(errors="replace").strip()
                raise RuntimeError(_error(
                    "pulse_capture_stopped",
                    status=proc.returncode,
                    error=stderr,
                ))

            count += 1
            if any(pcm):
                signal += 1
            if count == 1 or count % 250 == 0:
                logger.info(
                    "Voice PulseAudio: speaker -> call frames={} signal_frames={} bytes={}",
                    count,
                    signal,
                    len(pcm),
                )
            yield AudioFrame(
                pcm=pcm,
                sample_rate=devices.config.sample_rate,
                channels=devices.config.channels,
            )
    finally:
        await _stop_process(proc)


async def _stop_process(proc: asyncio.subprocess.Process) -> None:
    if proc.returncode is not None:
        return
    proc.terminate()
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
