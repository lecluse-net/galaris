"""Bounded telemetry for effect recovery, without arguments or tool outputs."""

from typing import Literal

import logfire
from loguru import logger

_outcomes = logfire.metric_counter(
    "harness_effect_recovery_total",
    unit="1",
    description="Durable tool effect transitions and reconciliation outcomes.",
)


def observe_recovery(
    outcome: Literal[
        "started", "completed", "rejected", "unknown", "recovered", "blocked", "replayed"
    ],
    *,
    run_id: str,
    operation_id: str = "",
) -> None:
    _outcomes.add(1, {"outcome": outcome})
    logger.bind(run_id=run_id, operation_id=operation_id, recovery_outcome=outcome).log(
        "WARNING" if outcome in {"unknown", "blocked"} else "DEBUG",
        "Harness effect recovery: {}",
        outcome,
    )
