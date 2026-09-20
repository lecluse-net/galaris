"""Low-cardinality gauges of durable queue age and observation progress."""

from datetime import datetime, timezone
import logfire
from sqlalchemy import DateTime, case, cast, func, select
from core.database import get_db
from .models import ProcessRun, ProcessStartJob
from . import registry

_queue_age = logfire.metric_gauge("process_oldest_pending_seconds", unit="s")
_pending = logfire.metric_gauge("process_pending_jobs")
_unknown = logfire.metric_gauge("process_unknown_runs")
_observation_age = logfire.metric_gauge("process_oldest_observation_seconds", unit="s")


async def record_progress_metrics() -> None:
    now = datetime.now(timezone.utc)
    db = get_db()
    for engine_code in registry.codes():
        count, oldest = (
            await db.execute(
                select(func.count(ProcessStartJob.id), func.min(ProcessStartJob.created_at))
                .join(ProcessRun, ProcessRun.id == ProcessStartJob.run_id)
                .where(ProcessRun.engine_code == engine_code, ProcessStartJob.status == "pending")
            )
        ).one()
        labels = {"engine": engine_code}
        _pending.set(int(count or 0), labels)
        _queue_age.set(max(0, (now - oldest).total_seconds()) if oldest else 0, labels)
        uncertain = await db.scalar(
            select(func.count(ProcessRun.id)).where(
                ProcessRun.engine_code == engine_code, ProcessRun.status == "unknown"
            )
        )
        _unknown.set(int(uncertain or 0), labels)
        observed, created = (
            await db.execute(
                select(
                    func.min(
                        func.coalesce(
                            case(
                                (
                                    func.pg_input_is_valid(
                                        ProcessRun.engine_metadata["last_observed_at"].astext,
                                        "timestamp with time zone",
                                    ),
                                    cast(
                                        ProcessRun.engine_metadata["last_observed_at"].astext,
                                        DateTime(timezone=True),
                                    ),
                                ),
                                else_=None,
                            ),
                            ProcessRun.created_at,
                        )
                    ),
                    func.min(ProcessRun.created_at),
                ).where(
                    ProcessRun.engine_code == engine_code,
                    ProcessRun.status.in_(("running", "waiting", "unknown", "cancelling")),
                )
            )
        ).one()
        try:
            # Include unobserved runs: a recent successful poll must not hide
            # another run that has never made observation progress.
            reference = observed or created
            age = max(0, (now - reference).total_seconds()) if reference else 0
        except ValueError, TypeError:
            age = max(0, (now - created).total_seconds()) if created else 0
        _observation_age.set(age, labels)
