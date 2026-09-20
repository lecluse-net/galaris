"""Bound CPU, memory and wall time independently from the scheduler event loop."""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from .ical import DueCalendarAction, ParsedEvent

_slots = asyncio.Semaphore(2)


async def _calculate(
    mode: str, content: bytes, start: datetime, end: datetime, *flags: str
) -> bytes:
    if len(content) > 5 * 1024 * 1024:
        raise ValueError("Calendar resource exceeds 5 MiB")
    async with asyncio.timeout(10), _slots:
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            str(Path(__file__).with_name("ical_worker.py")),
            mode,
            start.isoformat(),
            end.isoformat(),
            *flags,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(5):
                stdout, _ = await process.communicate(content)
            if process.returncode != 0:
                raise ValueError(
                    "Calendar calculation exceeded its resource limits or contains an invalid recurrence"
                )
            return stdout
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def events_between(content: bytes, start: datetime, end: datetime) -> list[ParsedEvent]:
    return TypeAdapter(list[ParsedEvent]).validate_json(
        await _calculate("events", content, start, end)
    )


async def due_actions(
    content: bytes,
    start: datetime,
    end: datetime,
    *,
    trigger_on_start: bool,
    trigger_on_alarm: bool,
) -> list[DueCalendarAction]:
    return TypeAdapter(list[DueCalendarAction]).validate_json(
        await _calculate(
            "actions",
            content,
            start,
            end,
            "1" if trigger_on_start else "0",
            "1" if trigger_on_alarm else "0",
        )
    )
