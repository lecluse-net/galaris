"""Let a Lab command publish its effects and receipt in one transaction."""

from collections.abc import Generator
from contextlib import contextmanager

from core.database import get_db


@contextmanager
def atomic_command() -> Generator[None]:
    session = get_db()
    previous = session.info.get("lab_atomic_command", False)
    session.info["lab_atomic_command"] = True
    try:
        yield
    finally:
        session.info["lab_atomic_command"] = previous


async def publish() -> None:
    session = get_db()
    if session.info.get("lab_atomic_command"):
        await session.flush()
    else:
        await session.commit()
