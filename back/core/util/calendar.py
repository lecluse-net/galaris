"""Calendar interval helpers shared by monthly reporting surfaces."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


def local_timezone_name() -> str:
    """Return the configured IANA timezone, falling back safely to UTC."""

    timezone_name = (os.getenv("TZ") or "UTC").strip() or "UTC"
    try:
        ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        return "UTC"
    return timezone_name


def month_bounds(
    month: str | None,
    *,
    now: datetime | None = None,
    timezone_name: str | None = None,
) -> tuple[str, datetime, datetime]:
    """Return a local calendar month as a half-open UTC interval."""

    local_zone = ZoneInfo(timezone_name or local_timezone_name())
    reference = (now or datetime.now(timezone.utc)).astimezone(local_zone)
    normalized = month or f"{reference.year:04d}-{reference.month:02d}"
    match = _MONTH_PATTERN.fullmatch(normalized)
    if match is None:
        raise ValueError("month must use the YYYY-MM format")

    year = int(match.group(1))
    month_number = int(match.group(2))
    local_start = datetime(year, month_number, 1, tzinfo=local_zone)
    if month_number == 12:
        local_end = datetime(year + 1, 1, 1, tzinfo=local_zone)
    else:
        local_end = datetime(year, month_number + 1, 1, tzinfo=local_zone)
    return (
        normalized,
        local_start.astimezone(timezone.utc),
        local_end.astimezone(timezone.utc),
    )


__all__ = ["local_timezone_name", "month_bounds"]
