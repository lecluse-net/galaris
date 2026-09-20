"""Bounded, opt-in pruning of recovered diagnostic payloads, never identities."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from core.database import get_db
from core.params import runtime_settings
from .models import FailureIncident, FailureIncidentTrace


async def prune_traces(*, preview: bool = False, batch_size: int = 100) -> int:
    """Keep unresolved incidents and all summaries, hashes and causal references.

    Trace payloads are diagnostic only: retries and runtime recovery do not read them.
    An explicit marker makes an intentionally expired trace distinguishable from an empty one.
    """
    days = runtime_settings.INCIDENT_TRACE_RETENTION_DAYS
    if days == 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    db = get_db()
    rows = list(
        (
            await db.scalars(
                select(FailureIncidentTrace)
                .join(FailureIncident, FailureIncident.id == FailureIncidentTrace.incident_id)
                .where(
                    FailureIncident.recovered_at < cutoff,
                    FailureIncidentTrace.created_at < cutoff,
                    FailureIncidentTrace.byte_size > 0,
                )
                .order_by(FailureIncidentTrace.created_at, FailureIncidentTrace.incident_id)
                .limit(max(1, min(batch_size, 500)))
                .with_for_update(of=FailureIncidentTrace, skip_locked=True)
            )
        ).all()
    )
    if not preview:
        for trace in rows:
            trace.payload = {"retention": "expired"}
            trace.truncated_fields = list(dict.fromkeys([*trace.truncated_fields, "$ (retention)"]))
            trace.byte_size = 0
        await db.flush()
    return len(rows)
