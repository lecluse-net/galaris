from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dream.models import DreamReceipt
from app.llm.models import LLMCall
from app.llm.user_attribution import backfill_call_users, call_users_backfilled
from app.task.models import Task
from core.user.models import User


@pytest.mark.asyncio
async def test_historical_attribution_preserves_original_requesters_and_unassigned_costs(db: AsyncSession) -> None:
    requester = User(email="attribution-requester@example.test", hashed_password="unused")
    operator = User(email="attribution-operator@example.test", hashed_password="unused")
    db.add_all([requester, operator])
    await db.flush()
    root = Task(id=uuid4(), label="Original mission", requester_user_id=requester.id)
    child = Task(id=uuid4(), label="Delegated work", source_task_id=root.id, requester_user_id=operator.id)
    receipt = DreamReceipt(mechanism_key="test", subject_kind="task_outcome",
                           subject_id=f"{child.id}:synthetic", status="success")
    maintenance = DreamReceipt(mechanism_key="test", subject_kind="memory_item",
                               subject_id=str(uuid4()), status="success")
    db.add_all([root, child, receipt, maintenance])
    await db.flush()

    archived = LLMCall(task_id=child.id, requester_user_id=operator.id, cost=0.25)
    archived.soft_delete()
    reflection = LLMCall(correlation_ref=f"dream-receipt:{receipt.id}")
    system = LLMCall(correlation_ref=f"dream-receipt:{maintenance.id}", requester_user_id=operator.id)
    direct = LLMCall(requester_user_id=operator.id)
    retained = LLMCall(task_id=child.id, user_id=operator.id)
    db.add_all([archived, reflection, system, direct, retained])
    await db.flush()
    assert not await call_users_backfilled(db)
    await backfill_call_users(db)
    assert await call_users_backfilled(db)

    root.requester_user_id = operator.id
    await db.flush()
    await backfill_call_users(db)
    rows = dict((await db.execute(
        select(LLMCall.id, LLMCall.user_id).execution_options(include_historized=True)
    )).tuples().all())
    assert rows[archived.id] == rows[reflection.id] == requester.id
    assert rows[direct.id] == rows[retained.id] == operator.id
    assert rows[system.id] is None
    historical = await db.get(LLMCall, archived.id, populate_existing=True, execution_options={"include_historized": True})
    assert historical is not None
    assert historical.requester_user_id == operator.id and historical.cost == 0.25
