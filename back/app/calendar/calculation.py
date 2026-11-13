"""Bound CPU, memory and wall time independently from the scheduler event loop."""

import asyncio
import sys
import json
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from .ical import DueCalendarAction, ParsedEvent

_slots = asyncio.Semaphore(2)


class CalendarCalculationError(ValueError):
    def __init__(self, code: str, location: str | None = None) -> None:
        self.code = code
        self.location = location
        super().__init__(f"Calendar calculation failed: {code}")


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
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(5):
                stdout, _ = await process.communicate(content)
            if process.returncode != 0:
                try:
                    failure = json.loads(stdout)
                    code = str(failure["error_category"])
                    location = str(failure["error_location"])
                except (ValueError, KeyError, TypeError):
                    code, location = f"worker_exit_{process.returncode}", None
                raise CalendarCalculationError(code, location)
            return stdout
        finally:
            if process.returncode is None:
                process.kill()
            await process.wait()


async def events_between(content: bytes, start: datetime, end: datetime, zone: str = "UTC", *, compact: bool = False) -> list[ParsedEvent]:
    return TypeAdapter(list[ParsedEvent]).validate_json(
        await _calculate("events", content, start, end, zone, "compact" if compact else "full")
    )


async def due_actions(
    content: bytes,
    start: datetime,
    end: datetime,
) -> list[DueCalendarAction]:
    return TypeAdapter(list[DueCalendarAction]).validate_json(
        await _calculate(
            "actions",
            content,
            start,
            end,
        )
    )
