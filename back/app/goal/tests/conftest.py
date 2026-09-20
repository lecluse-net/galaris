"""Isolated native document storage for Goal tests."""

from collections.abc import Iterator
from pathlib import Path

import pytest

from app.memory.storage import (
    NativeFileStorage,
    register_storage,
    reset_storage_registry,
)


@pytest.fixture(autouse=True)
def goal_document_storage(tmp_path: Path) -> Iterator[None]:
    reset_storage_registry()
    register_storage(NativeFileStorage(tmp_path, max_bytes=1_000_000))
    try:
        yield
    finally:
        reset_storage_registry()
