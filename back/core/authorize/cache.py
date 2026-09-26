"""Request-local RBAC snapshots; never retain decisions across HTTP requests."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from sqlalchemy import event
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction, UOWTransaction


@dataclass
class PrivilegeCache:
    active: bool = True
    entries: dict[Session, dict[tuple[int, int | None], frozenset[str]]] = field(
        default_factory=dict[Session, dict[tuple[int, int | None], frozenset[str]]],
    )


_cache: ContextVar[PrivilegeCache | None] = ContextVar("request_privileges", default=None)


def cached_privileges(session: Session) -> dict[tuple[int, int | None], frozenset[str]] | None:
    cache = _cache.get()
    if cache is None or not cache.active:
        return None
    # Do not let a cache hit skip SQLAlchemy's normal autoflush of pending changes.
    if session.new or session.dirty or session.deleted:
        cache.entries.pop(session, None)
        return None
    return cache.entries.setdefault(session, {})


@contextmanager
def request_privilege_cache() -> Generator[None]:
    """Share immutable role codes only for this HTTP request's database sessions."""
    cache = PrivilegeCache()
    token = _cache.set(cache)
    try:
        yield
    finally:
        # Detached tasks inherit ContextVars, so also deactivate the shared object.
        cache.active = False
        cache.entries.clear()
        _cache.reset(token)


def _invalidate(session: Session) -> None:
    cache = _cache.get()
    if cache is not None:
        cache.entries.pop(session, None)


def _after_flush(session: Session, _context: UOWTransaction) -> None:
    _invalidate(session)


def _after_transaction_end(session: Session, _transaction: SessionTransaction) -> None:
    _invalidate(session)


def _before_execute(state: ORMExecuteState) -> None:
    # This also invalidates textual SQL: its effects cannot be inferred safely.
    if not state.is_select:
        _invalidate(state.session)


event.listen(Session, "after_flush", _after_flush)
event.listen(Session, "after_transaction_end", _after_transaction_end)
event.listen(Session, "do_orm_execute", _before_execute)
