"""Reconcile skill revisions at the admitted Task's execution boundary.

The persisted skill library is the desired state; provider_metadata.skill_revision
is the last successfully projected state. Comparing them at every execution covers
all writers, including file tools and imports, without a client-owned notification.
Only the admitted run performs remote work. Administrative refreshes merely queue
an invalidation, so they cannot restart a runtime underneath an active Task.
"""

from __future__ import annotations

from collections.abc import Collection
from uuid import uuid4
from typing import Literal

from sqlalchemy import select, update

from app.agent import AgentRunRequest, agent_skill_revision, get_agent_record
from core.database import get_db

from .models import AgentHarness
from .registry import all_providers, get_provider

type SkillSyncStatus = Literal["not_applicable", "pending", "current", "error"]


async def skill_sync_status(agent_id: int) -> tuple[SkillSyncStatus, str | None]:
    """Compare durable desired state and receipt without contacting a runtime."""
    assignment = await get_db().scalar(
        select(AgentHarness).where(AgentHarness.agent_id == agent_id)
        .execution_options(populate_existing=True)
    )
    if assignment is None or assignment.provider_code not in _projecting_providers():
        return "not_applicable", None
    metadata = assignment.provider_metadata
    if metadata.get("skill_sync_error"):
        return "error", str(metadata["skill_sync_error"])
    if assignment.lifecycle_status != "ready":
        return "pending", None
    try:
        revision = await agent_skill_revision(agent_id)
    except Exception:
        return "error", "Skills cannot be read; retry after repairing the library."
    current = (
        metadata.get("skill_revision") == revision
        and metadata.get("skill_sync_requested") == metadata.get("skill_sync_applied")
    )
    return ("current" if current else "pending"), None


def _projecting_providers() -> tuple[str, ...]:
    return tuple(
        provider.code for provider in all_providers()
        if provider.containerized and "skills" in provider.capabilities()
    )


async def projected_skill_agent_ids(agent_ids: Collection[int] | None = None) -> list[int]:
    query = select(AgentHarness.agent_id).where(
        AgentHarness.provider_code.in_(_projecting_providers()),
        AgentHarness.lifecycle_status != "deprovisioning",
    )
    if agent_ids is not None:
        query = query.where(AgentHarness.agent_id.in_(agent_ids))
    return list(await get_db().scalars(query.order_by(AgentHarness.agent_id)))


async def request_skill_sync(agent_id: int) -> None:
    """Persist an invalidation, including for absent runtimes; never restart here."""
    await get_db().execute(
        update(AgentHarness)
        .where(
            AgentHarness.agent_id == agent_id,
            AgentHarness.provider_code.in_(_projecting_providers()),
            AgentHarness.lifecycle_status != "deprovisioning",
        )
        .values(provider_metadata=AgentHarness.provider_metadata.op("||")({
            "skill_sync_requested": str(uuid4()),
        }))
        .execution_options(synchronize_session=False)
    )
    await get_db().commit()


async def prepare_skill_execution(request: AgentRunRequest) -> None:
    """Fail closed before dispatch if the frozen runtime cannot receive current skills.

    Managed providers admit one Task at a time through the durable scheduler lease.
    A checkpoint may still refer to a running remote operation: reconciling that
    operation must retain its original skills and credentials. Pending changes
    apply at the next fresh execution, never underneath a remote continuation.
    """
    target = request.target
    if target is None or not target.target_ref.startswith("harness:"):
        return
    from .service import HarnessConflictError, agent_lock

    async with agent_lock(request.agent.id):
        db = get_db()
        assignment = await db.scalar(
            select(AgentHarness).where(AgentHarness.agent_id == request.agent.id)
            .execution_options(populate_existing=True)
        )
        if (
            assignment is None
            or target.target_ref != f"harness:{assignment.id}"
            or target.provider_code != assignment.provider_code
            or target.revision != str(assignment.revision)
            or assignment.lifecycle_status != "ready"
        ):
            raise HarnessConflictError("The frozen Harness is no longer ready or selected.")
        if assignment.provider_code not in _projecting_providers():
            return
        if request.resume_checkpoint is not None:
            return
        if request.task_id is None:
            raise HarnessConflictError("Skill synchronization requires an admitted Task.")
        agent = await get_agent_record(request.agent.id)
        if agent is None:
            raise HarnessConflictError("The Harness agent no longer exists.")
        provider = get_provider(assignment.provider_code)
        assignment_id = assignment.id
        metadata = dict(assignment.provider_metadata)
        requested = metadata.get("skill_sync_requested")
        try:
            revision = await agent_skill_revision(agent.id)
            if (
                metadata.get("skill_revision") == revision
                and requested == metadata.get("skill_sync_applied")
                and not metadata.get("skill_sync_error")
            ):
                return
            # Invalidate the receipt before remote effects, including cancellation
            # or process death halfway through a destructive tree replacement.
            await db.execute(
                update(AgentHarness).where(AgentHarness.id == assignment_id)
                .values(provider_metadata=AgentHarness.provider_metadata.op("||")({
                    "skill_revision": None,
                }))
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            # A concurrent edit must not turn a mixed or outdated copy into a
            # certified revision. Retry once; continuous editing keeps it pending.
            for _ in range(2):
                await provider.run_action(agent, "refresh")
                current = await agent_skill_revision(agent.id)
                if current == revision:
                    await db.execute(
                        update(AgentHarness).where(AgentHarness.id == assignment_id)
                        .values(provider_metadata=AgentHarness.provider_metadata.op("||")({
                            "skill_revision": revision,
                            "skill_sync_applied": requested,
                            "skill_sync_error": None,
                        }))
                        .execution_options(synchronize_session=False)
                    )
                    await db.commit()
                    return
                revision = current
            raise RuntimeError("Skills changed during synchronization; retry the Task.")
        except Exception as exc:
            # Do not expose transport exceptions, which may contain credentials.
            # Keep the invalid receipt and any newer invalidation atomically.
            await db.rollback()
            await db.execute(
                update(AgentHarness).where(AgentHarness.id == assignment_id)
                .values(provider_metadata=AgentHarness.provider_metadata.op("||")({
                    "skill_sync_error": "Skill synchronization failed; retry the Task.",
                }))
                .execution_options(synchronize_session=False)
            )
            await db.commit()
            raise RuntimeError("Skill synchronization failed; retry the Task.") from exc
