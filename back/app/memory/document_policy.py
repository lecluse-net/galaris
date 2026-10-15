"""Scope trusted writes to a legacy Dataset without granting resource access."""

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

_dataset_writer: ContextVar[UUID | None] = ContextVar("dataset_document_writer", default=None)

def dataset_writer_active(document_id: UUID) -> bool:
    return _dataset_writer.get() == document_id


@contextmanager
def dataset_write_scope(document_id: UUID) -> Generator[None]:
    token = _dataset_writer.set(document_id)
    try:
        yield
    finally:
        _dataset_writer.reset(token)
