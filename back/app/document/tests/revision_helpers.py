"""Exercise the durable revision worker with a clock instead of real waiting."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import pytest

from app.document import automation, revision_batching


@pytest.fixture
def revision_clock(db, monkeypatch):
    class Clock:
        now = datetime.now(timezone.utc) + timedelta(seconds=1)

        def advance(self, seconds=301):
            self.now += timedelta(seconds=seconds)

        async def settle(self):
            self.advance()
            while await automation.process_next():
                pass

    clock = Clock()

    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock.now

    @asynccontextmanager
    async def session():
        try:
            yield db
            await db.commit()
        except BaseException:
            await db.rollback()
            raise

    monkeypatch.setattr(revision_batching, "utcnow", lambda: clock.now)
    monkeypatch.setattr(automation, "datetime", FrozenDatetime)
    monkeypatch.setattr(automation, "get_db_session", session)
    return clock
