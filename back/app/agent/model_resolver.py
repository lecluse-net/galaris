"""Single, auditable model resolution for an agent run."""

from __future__ import annotations

from app.llm import model_usages

from typing import Any

from core.i18n import render_prompt, t
from app.llm import llm_service
from app.llm.provider_models import LLM

from .contracts import (
    AgentModelConfigurationError,
    ExecutionEffort,
    ReasoningEffort,
    ResolvedModel,
)


async def resolve_agent_profile_model(
    agent: Any,
    model_field: str,
) -> LLM | None:
    """Resolve an orchestration model from the agent's single effective profile."""
    return await llm_service.get_profile_llm(model_field, agent=agent)


async def has_agent_profile_model(
    agent: Any,
    model_field: str,
) -> bool:
    """Return whether the agent's single effective profile configures the usage."""
    return await resolve_agent_profile_model(agent, model_field) is not None


async def require_agent_profile_model(
    agent: Any,
    model_field: str,
) -> LLM:
    """Resolve a configured usage or fail before calling a model runtime."""
    llm = await resolve_agent_profile_model(agent, model_field)
    if llm is None:
        raise AgentModelConfigurationError(
            f"No model is configured for usage {model_field!r} in the effective profile."
        )
    return llm


async def resolve_model(
    agent: Any,
    effort: ExecutionEffort,
    language: str = "en",
    reasoning_effort_override: ReasoningEffort | None = None,
) -> ResolvedModel:
    """Freeze the effective model before the driver starts.

    ``high`` uses its dedicated setting when configured and otherwise falls back to the
    agent's standard model in an explicit, traceable way.
    """
    llm = None
    model_field = model_usages.EXECUTOR
    fallback_used = False
    if effort == "high":
        model_field = model_usages.EXECUTOR_HIGH
        llm = await llm_service.get_profile_llm(
            model_field, agent=agent
        )
        fallback_used = llm is None
    if llm is None:
        model_field = model_usages.EXECUTOR
        llm = await llm_service.get_llm_for_agent(agent)
    if llm is None:
        agent_code = str(getattr(agent, "code", "") or "?")
        raise AgentModelConfigurationError(
            render_prompt(
                t("agent_api.errors.executor_model_missing", language),
                agent_code=repr(agent_code),
                effort=effort,
            )
        )
    return ResolvedModel(
        id=int(llm.id),
        code=str(llm.code),
        model_name=str(llm.llm_name),
        label=str(llm.label),
        requested_effort=effort,
        reasoning_effort=(
            reasoning_effort_override
            or await llm_service.get_profile_reasoning_effort(
                model_field,
                agent=agent,
            )
        ),
        fallback_used=fallback_used,
    )


async def resolve_conversation_model(
    agent: Any,
    language: str = "en",
) -> ResolvedModel:
    """Freeze the conversation model from the agent's effective profile."""

    llm = await llm_service.get_profile_llm(model_usages.CONVERSATION, agent=agent)
    if llm is None:
        agent_code = str(getattr(agent, "code", "") or "?")
        raise AgentModelConfigurationError(
            render_prompt(
                t("agent_api.errors.executor_model_missing", language),
                agent_code=repr(agent_code),
                effort="standard",
            )
        )
    return ResolvedModel(
        id=int(llm.id),
        code=str(llm.code),
        model_name=str(llm.llm_name),
        label=str(llm.label),
        requested_effort="standard",
        reasoning_effort=await llm_service.get_profile_reasoning_effort(
            model_usages.CONVERSATION,
            agent=agent,
        ),
        fallback_used=False,
    )
