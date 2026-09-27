"""Wakeups follow the durable transaction, including savepoint outcomes."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from core.database import after_commit, get_db_session


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["commit", "rollback", "close", "failed_transaction"])
async def test_callbacks_only_run_after_a_successful_commit(committed_database, outcome):
    received = []
    async with get_db_session() as db:
        await db.execute(text("SELECT 1"))
        after_commit(lambda: received.append("replaced"), key="work")
        after_commit(lambda: received.append("work"), key="work")
        assert received == []
        if outcome == "commit":
            await db.commit()
            assert received == ["work"]
        elif outcome == "rollback":
            await db.rollback()
        elif outcome == "close":
            await db.close()
        else:
            with pytest.raises(DBAPIError):
                await db.execute(text("SELECT 1 / 0"))
            await db.rollback()
        # A later transaction must never revive discarded callbacks.
        await db.execute(text("SELECT 1"))
        await db.commit()
    assert received == (["work"] if outcome == "commit" else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("savepoint_commits", [False, True])
@pytest.mark.parametrize("outer_commits", [False, True])
async def test_savepoint_notifications_follow_outer_commit(
    committed_database, savepoint_commits, outer_commits,
):
    received = []
    async with get_db_session() as db:
        after_commit(lambda: received.append("outer"), key="outer")
        savepoint = await db.begin_nested()
        await db.execute(text("SELECT 1"))
        after_commit(lambda: received.append("inner"), key="inner")
        if savepoint_commits:
            await savepoint.commit()
        else:
            await savepoint.rollback()
        assert received == []
        if outer_commits:
            await db.commit()
        else:
            await db.rollback()
    assert received == (["outer"] + (["inner"] if savepoint_commits else []) if outer_commits else [])


@pytest.mark.asyncio
async def test_failed_wakeup_does_not_turn_a_commit_into_failure(committed_database):
    received = []

    def broken():
        raise RuntimeError("Synthetic notification failure")

    async with get_db_session():
        after_commit(broken, key="broken")
        after_commit(lambda: received.append("healthy"), key="healthy")
    assert received == ["healthy"]
