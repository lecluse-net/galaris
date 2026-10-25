"""Cost evidence is separate from numeric counters: an unknown amount is not free."""

from collections.abc import Iterable
from math import fsum, isfinite
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field

CostQuality = Literal["exact", "estimated", "partial", "unknown"]
COST_EVIDENCE_KEY = "_galaris_cost"


class CallCost(BaseModel):
    call_id: UUID
    status: str
    purpose: str | None = None
    cost: float | None
    inference_cost: float | None
    quality: CostQuality
    inference_quality: CostQuality
    source: str


class CostSummary(BaseModel):
    version: Literal["llm-cost-summary/v1"] = "llm-cost-summary/v1"
    currency: Literal["USD"] = "USD"
    calls: int = 0
    exact_calls: int = 0
    estimated_calls: int = 0
    unknown_calls: int = 0
    running_calls: int = 0
    failed_calls: int = 0
    subscription_calls: int = 0
    recorded_cost: float = 0
    total_cost: float | None = None
    inference_cost: float | None = None
    quality: CostQuality = "unknown"
    entries: list[CallCost] = Field(default_factory=list[CallCost])


def amount(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (float, int, str)):
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return number if isfinite(number) and number >= 0 else None


def call_cost(
    *, call_id: UUID, cost: float, inference_cost: float, cost_estimated: bool,
    is_subscription: bool, status: str, usage: dict[str, Any], purpose: str | None = None,
) -> CallCost:
    raw_evidence = usage.get(COST_EVIDENCE_KEY)
    evidence = cast(dict[str, Any], raw_evidence) if isinstance(raw_evidence, dict) else {}
    inferred = amount(inference_cost)
    billed = amount(cost)
    if evidence.get("version") == "llm-cost/v1":
        source = str(evidence.get("source", "unknown"))
        quality: CostQuality = ("exact" if source == "provider" else
                                "estimated" if source == "pricing" else "unknown")
    else:
        source = "legacy"
        # Historical zero estimates lack evidence of a free tariff or token usage.
        quality = "exact" if not cost_estimated else "estimated" if inferred else "unknown"
    if inferred is None:
        quality = "unknown"
    inference_quality = quality
    if source == "legacy" and inferred == 0 and billed and not is_subscription:
        # inference_cost was added later with a zero default; an older positive
        # bill cannot establish that its inference value was actually zero.
        inferred = None
        inference_quality = "unknown"
    return CallCost(call_id=call_id, status=status, purpose=purpose,
        cost=0.0 if is_subscription else billed,
        inference_cost=inferred if quality != "unknown" else None,
        quality="exact" if is_subscription else quality if billed is not None else "unknown",
        inference_quality=inference_quality, source="subscription" if is_subscription else source)


def summarize_costs(calls: Iterable[CallCost]) -> CostSummary:
    values = list(calls)
    exact = sum(row.quality == "exact" for row in values)
    estimated = sum(row.quality == "estimated" for row in values)
    unknown = len(values) - exact - estimated
    running = sum(row.status == "running" for row in values)
    known = fsum(row.cost for row in values if row.cost is not None)
    complete = bool(values) and not unknown and not running
    return CostSummary(entries=values, calls=len(values), exact_calls=exact, estimated_calls=estimated,
        unknown_calls=unknown, running_calls=running,
        failed_calls=sum(row.status not in {"completed", "running"} for row in values),
        subscription_calls=sum(row.source == "subscription" for row in values),
        recorded_cost=known, total_cost=known if complete else None,
        inference_cost=(fsum(row.inference_cost for row in values if row.inference_cost is not None)
                        if values and not running and all(row.inference_cost is not None for row in values) else None),
        quality=("estimated" if estimated else "exact") if complete else
                "partial" if (exact or estimated) else "unknown")
