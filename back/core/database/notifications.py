"""Transaction-bound wakeups for the single-process application runtime."""

from collections.abc import Callable, Collection, Hashable, Mapping
from typing import cast

from loguru import logger
from sqlalchemy import event, inspect
from sqlalchemy.orm import Session, SessionTransaction, UOWTransaction

from .database import Base, get_db

_KEY = "galaris_commit_notifications"
type Callbacks = dict[SessionTransaction, dict[Hashable, Callable[[], None]]]


def after_commit(
    callback: Callable[[], None], *, key: Hashable, session: Session | None = None,
) -> None:
    """Coalesce a synchronous wakeup until the current transaction commits.

    Callbacks must only signal local waiters, never perform SQL or durable work.
    A released savepoint transfers its callbacks to the parent transaction;
    rollback (including a failed flush) or session close discards them.
    """
    session = session if session is not None else get_db().sync_session
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        transaction = session.begin()
    pending = cast(Callbacks, session.info.setdefault(_KEY, {}))
    pending.setdefault(transaction, {})[key] = callback


def watch_committed_changes(
    models: Mapping[type[Base], Collection[str]], callback: Callable[[], None],
) -> None:
    """Wake a domain after ORM insert/delete or relevant column changes.

    Register once during domain bootstrap. Heartbeats and trace-only updates
    stay silent when their columns are absent from the domain's field list.
    Bulk SQL writers must explicitly schedule their own post-commit wakeup.
    """
    def flushed(session: Session, _context: UOWTransaction) -> None:
        for entity in (*session.new, *session.dirty, *session.deleted):
            if not isinstance(entity, Base):
                continue
            fields = models.get(type(entity))
            if fields is None:
                continue
            state = inspect(entity)
            if entity in session.new or entity in session.deleted or any(
                state.attrs[field].history.has_changes() for field in fields
            ):
                after_commit(callback, key=callback, session=session)
                return

    event.listen(Session, "after_flush", flushed)


def _committed(session: Session) -> None:
    pending = cast(Callbacks, session.info.get(_KEY, {}))
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        return
    callbacks = pending.pop(transaction, {})
    if transaction.parent is not None:
        pending.setdefault(transaction.parent, {}).update(callbacks)
        return
    for callback in callbacks.values():
        try:
            callback()
        except Exception:
            # The commit already succeeded; a failed advisory wakeup must not
            # make its caller believe that durable work was rolled back.
            logger.exception("Post-commit runtime notification failed")


def _ended(session: Session, transaction: SessionTransaction) -> None:
    pending = cast(Callbacks, session.info.get(_KEY, {}))
    pending.pop(transaction, None)
    if transaction.parent is None or not pending:
        session.info.pop(_KEY, None)


event.listen(Session, "after_commit", _committed)
event.listen(Session, "after_transaction_end", _ended)
