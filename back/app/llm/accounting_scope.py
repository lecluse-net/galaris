"""Project persisted gateway costs onto one composed inference, even on failure."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID
from typing import Any
from math import fsum

from .cost_accounting import CallCost, CostSummary, call_cost, summarize_costs


@dataclass
class CallAccounting:
    costs: dict[UUID, float] = field(default_factory=dict[UUID, float])
    calls: dict[UUID, CallCost] = field(default_factory=dict[UUID, CallCost])

    @property
    def cost(self) -> float:
        return fsum(self.costs.values())

    def snapshot(self) -> CostSummary:
        return summarize_costs(self.calls.values())


_scopes: ContextVar[tuple[CallAccounting, ...]] = ContextVar("llm_call_accounting", default=())


def record_persisted_call_cost(
    call_id: UUID, cost: float, *, inference_cost: float | None = None,
    cost_estimated: bool = False, is_subscription: bool = False, status: str = "completed",
    usage: dict[str, Any] | None = None, purpose: str | None = None,
) -> None:
    for scope in _scopes.get():
        scope.costs[call_id] = cost
        scope.calls[call_id] = call_cost(call_id=call_id, cost=cost,
            inference_cost=cost if inference_cost is None else inference_cost,
            cost_estimated=cost_estimated, is_subscription=is_subscription,
            status=status, usage=usage or {}, purpose=purpose)


@contextmanager
def llm_call_accounting() -> Generator[CallAccounting]:
    """Include nested requests, replacing repeated updates of the same call."""
    accounting = CallAccounting()
    token = _scopes.set((*_scopes.get(), accounting))
    try:
        yield accounting
    finally:
        _scopes.reset(token)
