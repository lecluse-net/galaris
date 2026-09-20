"""Manual Talk call test with echo through PulseAudio.

This validates the phase-one bridge without Hermes: incoming Talk -> PulseAudio source ->
loopback module -> PulseAudio sink -> outgoing Talk.

Usage after rebuilding the backend:
    docker compose exec backend python scripts/manual_test.py tests/manual/talk_call_pulse_loopback.py
"""

import asyncio
import os

from loguru import logger

from app.voice import PulseAudioBridge, VoiceSession
from bridge.nextcloud.call import TalkCall

CONNECTION_ID = int(os.getenv("TALK_CONNECTION_ID", "1"))
ROOM_TOKEN = os.getenv("TALK_ROOM_TOKEN", "").strip()
DURATION_S = int(os.getenv("TALK_DURATION_S", "30"))
OUTGOING_CALL = os.getenv("TALK_OUTGOING_CALL", "1").strip().lower() not in {"0", "false", "no"}
RING_ATTEMPTS = int(os.getenv("TALK_RING_ATTEMPTS", "3"))
RING_INTERVAL_S = float(os.getenv("TALK_RING_INTERVAL_S", "8"))
HPB_URL = os.getenv("TALK_HPB_URL", "").strip()

_LOG_FILE = "/tmp/galaris-diagnostics/talk_call_pulse_loopback.log"


async def main() -> None:
    if not ROOM_TOKEN:
        raise ValueError("TALK_ROOM_TOKEN is required")
    logger.add(_LOG_FILE, level="DEBUG", mode="w", backtrace=False, diagnose=False)
    logger.info(
        "=== Talk PulseAudio loopback POC: starting (connection={}, room={}) ===",
        CONNECTION_ID,
        ROOM_TOKEN,
    )
    transport = await TalkCall.from_connection_id(
        CONNECTION_ID,
        hpb_url=HPB_URL,
        start_call=OUTGOING_CALL,
        ring_attempts=RING_ATTEMPTS,
        ring_interval_s=RING_INTERVAL_S,
    )
    logger.info("PulseAudio loopback POC: HPB={} self_id={}", transport._hpb_url, transport._self_id)

    async with PulseAudioBridge(ROOM_TOKEN) as devices:
        await devices.connect_loopback()
        logger.info(
            "PulseAudio loopback POC: source={} mic_sink={} sink={} monitor={}",
            devices.source_name,
            devices.mic_sink_name,
            devices.sink_name,
            devices.sink_monitor,
        )

        session = VoiceSession(transport, ROOM_TOKEN)
        task = asyncio.create_task(session.run_pulseaudio(devices=devices))
        try:
            logger.info(
                "PulseAudio loopback POC: call '{}' for {}s...",
                ROOM_TOKEN,
                DURATION_S,
            )
            await asyncio.sleep(DURATION_S)
        except asyncio.CancelledError:
            pass
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    logger.success("PulseAudio loopback POC complete")
