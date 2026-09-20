from typing import Any

from core.i18n import default_language, is_supported, render_prompt, t

from app.llm import llm_service
from . import agent_service


_PROFILE_PREVIEW_MAX_CHARS = 100


def _language(language: str | None) -> str:
    return language if is_supported(language) else default_language()


def _message(language: str, key: str, **values: Any) -> str:
    return render_prompt(t(f"agent_directory.{key}", language), **values)


def _boolean(language: str, value: bool) -> str:
    return _message(language, "yes" if value else "no")


def _single_line(value: str) -> str:
    return value.replace("\n", " ")


def _preview(value: str, max_chars: int = _PROFILE_PREVIEW_MAX_CHARS) -> str:
    single_line = _single_line(value)
    if len(single_line) <= max_chars:
        return single_line
    return f"{single_line[:max_chars - 3].rstrip()}..."


async def list_agents(limit: int = 50, *, language: str | None = None) -> str:
    """List virtual-company agents and their characteristics.

    Use this tool to identify, describe, or compare colleagues, roles, expertise, and
    collaboration options. Profile text is limited to 100 characters; call
    ``get_agent_details`` with an ID for the complete profile.
    """
    lang = _language(language)
    try:
        agents = await agent_service.get_all(limit=limit)
    except RuntimeError as e:
        return _message(lang, "database_error", error=e)
    except Exception as e:
        return _message(lang, "list_failed", error=e)

    if not agents:
        return _message(lang, "none")

    lines: list[str] = [_message(lang, "list_heading", count=len(agents)) + "\n"]

    # Every service below uses the context-bound SQLAlchemy AsyncSession. An
    # AsyncSession cannot execute concurrent statements safely, so resolving all
    # profiles through ``asyncio.gather`` can close the shared transaction while
    # ``agent_list`` is still running. The directory is bounded to 50 rows; keep
    # these reads sequential within the tool transaction.
    resolved_llms = [
        await llm_service.get_llm_for_agent(agent) for agent in agents
    ]
    for agent, resolved_llm in zip(agents, resolved_llms):
        lines.append(_message(lang, "id", value=agent.id))
        lines.append("  " + _message(
            lang, "name", value=f"{agent.first_name} {agent.last_name}"
        ))
        if agent.title:
            gender = _message(
                lang, "male" if agent.title.gender == "M" else "female"
            )
            lines.append("  " + _message(
                lang, "title", value=agent.title.label, gender=gender
            ))
        if agent.job_title:
            lines.append("  " + _message(
                lang, "job_title", value=_preview(agent.job_title)
            ))
        if agent.job_description:
            desc = _preview(agent.job_description)
            lines.append("  " + _message(lang, "description", value=desc))
        if agent.personality:
            pers = _preview(agent.personality)
            lines.append("  " + _message(lang, "personality", value=pers))
        if resolved_llm:
            lines.append("  " + _message(
                lang,
                "assigned_llm",
                label=resolved_llm.label,
                model=resolved_llm.llm_name,
            ))
        lines.append("")

    return "\n".join(lines)


async def get_agent_details(
    agent_id: int,
    *,
    language: str | None = None,
) -> str:
    """Return one complete agent profile without text truncation."""
    lang = _language(language)
    try:
        agent = await agent_service.get(agent_id)
    except RuntimeError as e:
        return _message(lang, "database_error", error=e)
    except Exception as e:
        return _message(lang, "details_failed", error=e)

    if agent is None:
        return _message(lang, "not_found", agent_id=agent_id)

    lines: list[str] = [
        _message(lang, "profile_heading", agent_id=agent.id) + "\n"
    ]

    if agent.code:
        lines.append(_message(lang, "code", value=agent.code))
    lines.append(_message(
        lang, "name", value=f"{agent.first_name} {agent.last_name}"
    ))
    if agent.title:
        gender = _message(
            lang, "male" if agent.title.gender == "M" else "female"
        )
        lines.append(_message(
            lang, "title", value=agent.title.label, gender=gender
        ))
    if agent.job_title:
        lines.append(_message(lang, "job_title", value=agent.job_title))
    if agent.job_description:
        lines.append(_message(
            lang, "description", value=_single_line(agent.job_description)
        ))
    if agent.personality:
        lines.append(_message(
            lang, "personality", value=_single_line(agent.personality)
        ))
    resolved_llm = await llm_service.get_llm_for_agent(agent)
    if resolved_llm:
        lines.append(_message(
            lang,
            "assigned_llm",
            label=resolved_llm.label,
            model=resolved_llm.llm_name,
        ))
    from app.agent import resolve_pipeline_policy, effective_tool_profile, validate_agent_driver

    driver_code = validate_agent_driver(agent.agent_driver, require_available=False)
    policy = resolve_pipeline_policy(driver_code)
    capabilities = await effective_tool_profile(agent.id, driver_code)
    lines.append(_message(lang, "driver", value=driver_code))
    lines.append(_message(
        lang, "planner_enabled", value=_boolean(lang, policy.use_planner)
    ))
    lines.append(_message(
        lang, "briefing_enabled", value=_boolean(lang, policy.use_briefing)
    ))
    lines.append(_message(
        lang, "voice_calling", value=_boolean(lang, capabilities.voice_calling)
    ))
    lines.append(_message(
        lang, "file_tools", value=_boolean(lang, capabilities.file_tools)
    ))
    lines.append(_message(
        lang, "console_execution", value=_boolean(lang, capabilities.console_execution)
    ))

    return "\n".join(lines)
