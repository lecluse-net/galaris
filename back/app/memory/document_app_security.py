"""Bounded, strict JSON and database-backed application write quotas."""

import json
import math
from datetime import datetime
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import func, select

from core.database import get_db

from .models import DocumentAppWriteBudget
from .service import MemoryPermissionError

MAX_WRITES = 30
MAX_WRITE_BYTES = 4_000_000
WINDOW_SECONDS = 60


class AppConsentRequired(MemoryPermissionError):
    """The current human has not approved this exact version and binding."""


class AppWriteLimitError(Exception):
    """No mutation was performed because the durable budget is exhausted."""


def encode_app_data(value: JsonValue) -> str:
    """Bound work before serializing; arbitrary text remains data, never executable HTML."""
    stack: list[tuple[JsonValue, int]] = [(value, 0)]
    nodes = 0
    while stack:
        entry, depth = stack.pop()
        nodes += 1
        if depth > 32 or nodes > 20_000:
            raise ValueError("Dataset application data exceeds the depth or node limit.")
        if isinstance(entry, float) and not math.isfinite(entry):
            raise ValueError("Dataset application data requires finite JSON numbers.")
        if isinstance(entry, dict):
            stack.extend((child, depth + 1) for child in entry.values())
        elif isinstance(entry, list):
            stack.extend((child, depth + 1) for child in entry)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    if len(encoded.encode("utf-8")) > 2_000_000:
        raise ValueError("Dataset application data exceeds 2,000,000 bytes.")
    return encoded


async def consume_write_budget(user_id: int, dataset_id: UUID, size: int) -> None:
    """Caller holds the Dataset row lock; reservation commits with the content revision."""
    db = get_db()
    now: datetime = (await db.execute(select(func.clock_timestamp()))).scalar_one()
    budget = await db.scalar(select(DocumentAppWriteBudget).where(
        DocumentAppWriteBudget.user_id == user_id, DocumentAppWriteBudget.dataset_id == dataset_id,
    ).execution_options(populate_existing=True))
    if budget is None:
        budget = DocumentAppWriteBudget(user_id=user_id, dataset_id=dataset_id,
                                        window_start=now, writes=0, bytes_written=0)
        db.add(budget)
    if (now - budget.window_start).total_seconds() >= WINDOW_SECONDS:
        budget.window_start, budget.writes, budget.bytes_written = now, 0, 0
    if budget.writes >= MAX_WRITES or budget.bytes_written + size > MAX_WRITE_BYTES:
        raise AppWriteLimitError("Dataset application write budget exhausted. Retry after one minute.")
    budget.writes += 1
    budget.bytes_written += size
