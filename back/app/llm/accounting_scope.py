"""Project persisted gateway costs onto one composed inference, even on failure."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class CallAccounting:
    costs: dict[UUID, float] = field(default_factory=dict[UUID, float])

    @property
    def cost(self) -> float:
        return sum(self.costs.values())


_scopes: ContextVar[tuple[CallAccounting, ...]] = ContextVar("llm_call_accounting", default=())


def record_persisted_call_cost(call_id: UUID, cost: float) -> None:
    for scope in _scopes.get():
        scope.costs[call_id] = cost


@contextmanager
def llm_call_accounting() -> Generator[CallAccounting]:
    """Include nested requests, replacing repeated updates of the same call."""
    accounting = CallAccounting()
    token = _scopes.set((*_scopes.get(), accounting))
    try:
        yield accounting
    finally:
        _scopes.reset(token)
