"""Resolve Hermes approvals through messenger choice interactions."""

from __future__ import annotations

from loguru import logger

from app.messenger.interactions import ChoiceResolution, PendingChoice, register_choice_handler

from . import client
from .client import HermesTarget

HERMES_APPROVAL_INTERACTION = "hermes_approval"


async def _handle_hermes_approval(
    interaction: PendingChoice,
    resolution: ChoiceResolution,
) -> None:
    metadata = dict(interaction.metadata or {})
    run_id = str(metadata.get("run_id") or "")
    if not run_id:
        logger.warning("Hermes interaction {} has no run_id", interaction.id)
        return
    if resolution.option_id is None:
        logger.warning("Hermes interaction {} has no option; ignoring free text", interaction.id)
        return

    from app.agent import get_agent_record
    from .config_service import execution_snapshot

    agent = await get_agent_record(interaction.agent_id) if interaction.agent_id else None
    if agent is None:
        logger.warning("Hermes interaction {} has no resolvable agent", interaction.id)
        return

    try:
        target = HermesTarget.from_config(
            await execution_snapshot(agent),
            agent_code=agent.code,
        )
        await client.submit_run_approval(target, run_id, resolution.option_id)
        logger.info(
            "Hermes approval submitted: interaction={} run={} choice={}",
            interaction.id,
            run_id,
            resolution.option_id,
        )
    except (client.HermesRunNotFound, client.HermesApprovalNotPending):
        # Hermes run state is process-local. A restart, timeout, or resolution through
        # another client makes this persisted interaction permanently stale, so consuming
        # it is safer than replaying the same response forever.
        logger.warning(
            "Hermes approval is no longer pending; consuming stale interaction={} run={}",
            interaction.id,
            run_id,
        )
    except Exception:
        logger.exception(
            "Failed to submit Hermes approval: interaction={} run={}",
            interaction.id,
            run_id,
        )
        raise


register_choice_handler(HERMES_APPROVAL_INTERACTION, _handle_hermes_approval)
