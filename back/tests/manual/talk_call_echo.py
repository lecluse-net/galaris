"""Manual Nextcloud Talk call echo proof of concept (phase zero).

The agent (bot) starts or joins a room call through Janus/HPB and echoes the audio it hears for
about ``DURATION_S`` seconds. It uses no STT, TTS, or Hermes and validates the complete
WebRTC/Janus/Opus pipeline against real infrastructure.

Usage from the backend container:
    1. Set TALK_CONNECTION_ID to a Nextcloud Talk connection and TALK_ROOM_TOKEN to the room where you
       start or receive a call from your Talk client.
    2. Run:
       docker compose exec backend python scripts/manual_test.py tests/manual/talk_call_echo.py
    3. Answer the call when OUTGOING_CALL=1, then speak; you should hear the echo.
       Observe the WebSocket logs for signaling messages.

Media negotiation (call.py ``_negotiate_media`` / MCU) follows the spreed-signaling
specification but remains unvalidated; use this script to iterate on it. Enable the
DEBUG-level ``Talk call WS`` logs when needed.
"""

import asyncio
import os

from loguru import logger

from app.voice import VoiceSession
from bridge.nextcloud.call import TalkCall

# --- Configure these values. ---
CONNECTION_ID = int(os.getenv("TALK_CONNECTION_ID", "1"))
ROOM_TOKEN = os.getenv("TALK_ROOM_TOKEN", "").strip()
DURATION_S = int(os.getenv("TALK_DURATION_S", "30"))
OUTGOING_CALL = os.getenv("TALK_OUTGOING_CALL", "1").strip().lower() not in {"0", "false", "no"}
RING_ATTEMPTS = int(os.getenv("TALK_RING_ATTEMPTS", "3"))
RING_INTERVAL_S = float(os.getenv("TALK_RING_INTERVAL_S", "8"))
# Optional when Nextcloud does not publish HPB in /signaling/settings.
# Example: TALK_HPB_URL=wss://cloud.example.test/standalone-signaling
HPB_URL = os.getenv("TALK_HPB_URL", "").strip()

# Keep live traces outside the source tree.
_LOG_FILE = "/tmp/galaris-diagnostics/talk_call_echo.log"


async def main() -> None:
    if not ROOM_TOKEN:
        raise ValueError("TALK_ROOM_TOKEN is required")
    logger.add(_LOG_FILE, level="DEBUG", mode="w", backtrace=False, diagnose=False)
    logger.info("=== Talk echo POC: starting (connection={}, room={}) ===", CONNECTION_ID, ROOM_TOKEN)
    try:
        transport = await TalkCall.from_connection_id(
            CONNECTION_ID,
            hpb_url=HPB_URL,
            start_call=OUTGOING_CALL,
            ring_attempts=RING_ATTEMPTS,
            ring_interval_s=RING_INTERVAL_S,
        )
    except Exception:
        logger.opt(exception=True).error("from_connection_id failed")
        raise
    logger.info("Echo POC: HPB={} self_id={}", transport._hpb_url, transport._self_id)
    session = VoiceSession(transport, ROOM_TOKEN)

    logger.info(
        "Echo POC: {} call '{}' for {}s (ringing={}x/{}s)",
        "starts/joins" if OUTGOING_CALL else "joins",
        ROOM_TOKEN,
        DURATION_S,
        RING_ATTEMPTS if OUTGOING_CALL else 0,
        RING_INTERVAL_S,
    )
    task = asyncio.create_task(session.run_echo())
    try:
        await asyncio.sleep(DURATION_S)
    except asyncio.CancelledError:
        pass
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    logger.success("Echo POC complete")
