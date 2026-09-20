"""Low-cost PostgreSQL storage gauges, without scanning application payloads."""

import logfire
from sqlalchemy import text
from core.database import get_db

_bytes = logfire.metric_gauge("db_relation_storage_bytes", unit="By")
_rows = logfire.metric_gauge("db_relation_estimated_rows")


async def record_storage_metrics() -> None:
    rows = await get_db().execute(
        text("""
        SELECT c.relname, pg_total_relation_size(c.oid), greatest(c.reltuples, 0)
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind IN ('r', 'm')
    """)
    )
    for name, size, estimate in rows:
        labels = {"table": str(name)}
        _bytes.set(int(size), labels)
        _rows.set(int(estimate), labels)
