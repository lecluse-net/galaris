"""Manual test that creates virtual PulseAudio devices.

Usage from the backend container after rebuilding it:
    docker compose exec backend python scripts/manual_test.py tests/manual/voice_pulse_devices.py

The script starts the shared PulseAudio server if needed, creates a virtual source and sink,
displays the devices, then cleans them up.
"""

import asyncio
import os

from loguru import logger

from app.voice.audio_devices import PulseAudioBridge, PulseAudioConfig, pulseaudio_status

DURATION_S = int(os.getenv("VOICE_PULSE_DURATION_S", "10"))
_LOG_FILE = "/tmp/galaris-diagnostics/voice_pulse_devices.log"


async def main() -> None:
    logger.add(_LOG_FILE, level="DEBUG", mode="w", backtrace=False, diagnose=False)
    config = PulseAudioConfig.from_settings()
    logger.info("=== PulseAudio device test: starting root={} ===", config.root)

    status = await pulseaudio_status(config)
    logger.info("PulseAudio info:\n{}", status["info"].strip())

    async with PulseAudioBridge("manual", config=config) as devices:
        logger.info("Hermes microphone source: {}", devices.source_name)
        logger.info("Microphone injection sink: {}", devices.mic_sink_name)
        logger.info("Hermes speaker sink: {}", devices.sink_name)
        logger.info("Monitor sink: {}", devices.sink_monitor)
        logger.info("Runtime environment: {}", devices.runtime_env())

        status = await pulseaudio_status(config)
        logger.info("Sources:\n{}", status["sources"].strip())
        logger.info("Sinks:\n{}", status["sinks"].strip())
        logger.info("Keeping devices for {}s for inspection...", DURATION_S)
        await asyncio.sleep(DURATION_S)

    logger.success("PulseAudio device test complete")
