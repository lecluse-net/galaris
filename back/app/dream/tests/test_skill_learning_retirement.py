"""The legacy producer retires without losing policy or recorded effects."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.dream import DreamReceipt
from app.dream.dbadmin import register_dbadmin
from app.dream.registry import mechanisms, register_default_mechanisms
from core.dbadmin import DbAdminRegistry
from core.params import Param, Params, params_service, runtime_settings
from core.params.access import parameter_privileges


@pytest.mark.asyncio
async def test_upgrade_retires_dream_work_and_preserves_skill_thresholds(db, monkeypatch):
    monkeypatch.setattr(runtime_settings, "SKILL_LEARNING_MIN_EVIDENCE", 3)
    threshold = await db.get(Param, Params.SKILL_LEARNING_MIN_EVIDENCE)
    await db.delete(threshold)
    db.add_all([
        Param(name="DREAM_SKILL_LEARNING_MODE", value="learn"),
        Param(name="DREAM_SKILL_MIN_EVIDENCE", value="5"),
    ])
    historical_key = "skill.learn_task_outcome"
    running = DreamReceipt(
        mechanism_key=historical_key, subject_kind="task_skill_learning", subject_id=str(uuid4()),
        status="running", lease_token=uuid4(), lease_owner="synthetic-worker",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        prepared_payload={"synthetic": "pending proposal"},
    )
    finished = DreamReceipt(
        mechanism_key=historical_key, subject_kind="task_skill_learning", subject_id=str(uuid4()),
        status="success", result_count=1,
    )
    db.add_all([running, finished])
    await db.commit()

    register_default_mechanisms()
    assert historical_key not in {mechanism.key for mechanism in mechanisms()}
    registry = DbAdminRegistry()
    register_dbadmin(registry)
    retirement = next(item for item in registry.reconcilers if item.key.endswith("retire_skill_learning_receipts"))
    for _ in range(2):
        await params_service.sync()
        await retirement.handler(db)
        await db.commit()

    await db.refresh(running)
    await db.refresh(finished)
    assert running.status == "error" and running.lease_token is None
    assert running.prepared_payload == {"synthetic": "pending proposal"}
    assert finished.status == "success" and finished.result_count == 1
    assert not await db.scalar(select(Param.name).where(Param.name.startswith("DREAM_SKILL_")))
    assert not parameter_privileges(Params.SKILL_LEARNING_MIN_EVIDENCE)
    assert runtime_settings.SKILL_LEARNING_MIN_EVIDENCE == 5
