"""Reconcile legacy Harness selections with bridge parameters and OpenAI rows."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from core.dbadmin import DbAdminReconciler, DbAdminRegistry

from .models import AgentHarness, Harness
from .registry import all_providers


async def _backfill_selected_harnesses(session: AsyncSession) -> None:
    """Keep bridge selections out of the reusable OpenAI Messages table."""

    providers = {provider.code: provider for provider in all_providers()}
    assignments = list((await session.scalars(select(AgentHarness))).all())
    assigned_agents = {assignment.agent_id for assignment in assignments}

    for assignment in assignments:
        agent = await session.get(Agent, assignment.agent_id)
        harness = (
            await session.get(Harness, assignment.harness_id)
            if assignment.harness_id is not None
            else None
        )
        provider_code = (
            harness.provider_code
            if harness is not None
            else assignment.provider_code or (agent.agent_driver if agent is not None else "")
        )
        provider = providers.get(provider_code)
        if agent is None or provider is None:
            await session.delete(assignment)
            continue
        assignment.provider_code = provider.code
        assignment.capabilities = sorted(provider.capabilities())
        if provider.code == "openai_messages" and harness is not None:
            assignment.harness_id = harness.id
            agent.task_harness_id = harness.id
        else:
            assignment.harness_id = None
            agent.task_harness_id = None
        agent.agent_driver = provider.driver_code

    legacy_agents = list(
        (
            await session.scalars(
                select(Agent).where(
                    Agent.agent_driver != "internal",
                    Agent.id.not_in(assigned_agents),
                )
            )
        ).all()
    )
    for agent in legacy_agents:
        provider = providers.get(agent.agent_driver)
        if provider is None or provider.code == "openai_messages":
            agent.agent_driver = "internal"
            agent.task_harness_id = None
            continue
        session.add(
            AgentHarness(
                agent_id=agent.id,
                harness_id=None,
                provider_code=provider.code,
                lifecycle_status="ready",
                capabilities=sorted(provider.capabilities()),
            )
        )
        agent.task_harness_id = None

    bridge_rows = list(
        (
            await session.scalars(
                select(Harness).where(Harness.provider_code != "openai_messages")
            )
        ).all()
    )
    await session.flush()
    for row in bridge_rows:
        await session.delete(row)
    await session.flush()


def register_dbadmin(registry: DbAdminRegistry) -> None:
    registry.register_reconciler(
        DbAdminReconciler(
            key="app.harnesses.catalogue_runtime_backfill",
            handler=_backfill_selected_harnesses,
        )
    )
