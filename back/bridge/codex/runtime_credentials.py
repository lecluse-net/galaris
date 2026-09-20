"""Resolve Galaris-owned OpenAI credentials for the isolated Codex runtime."""

from __future__ import annotations

from app.agent import get_agent_record
from app.harnesses import resolve_agent_harness
from app.llm import ManagedRuntimeCredential, get_managed_runtime_credential
from app.mcp import mcp_token_service


async def resolve_for_system_token(token: str) -> ManagedRuntimeCredential:
    """Return fresh ChatGPT auth only for an agent currently using Codex."""

    normalized = token.strip()
    if not normalized:
        raise PermissionError("A managed-runtime bearer token is required.")
    matched = await mcp_token_service.get_enabled_system_token_by_value(normalized)
    if matched is None:
        raise PermissionError("The managed-runtime bearer token is invalid.")

    agent = await get_agent_record(matched.agent_id)
    if agent is None:
        raise LookupError("The managed runtime agent no longer exists.")
    target = await resolve_agent_harness(agent)
    if target is None or target.provider_code != "codex":
        raise PermissionError("The agent is not assigned to the Codex Harness.")
    if target.status not in {"provisioning", "ready"}:
        raise PermissionError("The Codex Harness is not active.")
    return await get_managed_runtime_credential("openai-codex")


__all__ = ["resolve_for_system_token"]
