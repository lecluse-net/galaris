"""Manually run the direct Talk → Galaris voice-agent pipeline.

The test uses the configured global STT resource, the selected agent driver and
model, and the agent's TTS voice. No messaging-platform shim is involved.

Usage:
    TALK_ROOM_TOKEN=<token> docker compose exec backend \
        python scripts/manual_test.py tests/manual/talk_call_agent.py
"""

from __future__ import annotations

import asyncio
import os

from loguru import logger

from app.voice import VoiceSession
from bridge.nextcloud.call import TalkCall


CONNECTION_ID = int(os.getenv("TALK_CONNECTION_ID", "1"))
AGENT_ID = int(os.getenv("TALK_AGENT_ID", "1"))
ROOM_TOKEN = os.getenv("TALK_ROOM_TOKEN", "").strip()
DURATION_S = int(os.getenv("TALK_DURATION_S", "90"))
OUTGOING_CALL = os.getenv("TALK_OUTGOING_CALL", "1").strip().lower() not in {
    "0",
    "false",
    "no",
}


async def main() -> None:
    if not ROOM_TOKEN:
        raise ValueError("TALK_ROOM_TOKEN is required")
    transport = await TalkCall.from_connection_id(
        CONNECTION_ID,
        start_call=OUTGOING_CALL,
        ring_attempts=3 if OUTGOING_CALL else 1,
    )
    session = VoiceSession(transport, ROOM_TOKEN)
    logger.info(
        "Direct voice call starting agent={} connection={} room={} duration={}s",
        AGENT_ID,
        CONNECTION_ID,
        ROOM_TOKEN,
        DURATION_S,
    )
    try:
        await asyncio.wait_for(
            session.run_agent(agent_id=AGENT_ID, language="fr"),
            timeout=float(DURATION_S),
        )
    except asyncio.TimeoutError:
        logger.info("Direct voice call duration reached")
    logger.success("Direct voice call complete")
