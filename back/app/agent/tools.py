import json
from typing import Any

from core.i18n import default_language, is_supported, render_prompt, t

from app.llm import llm_service
from . import agent_service


_PROFILE_PREVIEW_MAX_CHARS = 100
# Keep a directory page intact through ordinary Harness history compaction.
_DIRECTORY_PAGE_MAX_CHARS = 4_000


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


def _directory_page(
    items: list[dict[str, object]], *, offset: int, limit: int, has_more: bool,
) -> str:
    return json.dumps(
        {
            "items": items,
            "count": len(items),
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + len(items) if has_more else None,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


async def list_agents(
    limit: int = 50, *, offset: int = 0, language: str | None = None,
    team_id: int | None = None, team_name: str | None = None,
) -> str:
    """Return a compact JSON directory page; read full profiles with agent_get."""
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("offset must be nonnegative and limit must be between 1 and 500")
    if team_id is not None and team_id <= 0:
        raise ValueError("team_id must be positive")
    if team_name is not None:
        if not team_name.strip() or len(team_name) > 255:
            raise ValueError("team_name must contain between 1 and 255 characters")
        team_name = team_name.strip()
    lang = _language(language)
    try:
        # One lookahead row distinguishes a complete page from an unfinished list.
        agents = await agent_service.get_all(
            skip=offset, limit=limit + 1, team_id=team_id, team_name=team_name,
        )
    except RuntimeError as e:
        return _message(lang, "database_error", error=e)
    except Exception as e:
        return _message(lang, "list_failed", error=e)

    items: list[dict[str, object]] = []
    for agent in agents[:limit]:
        item: dict[str, object] = {
            "id": agent.id,
            "resource_uri": f"galaris://agent/{agent.id}",
            "code": _preview(agent.code),
            "name": _preview(f"{agent.first_name} {agent.last_name}".strip(), 200),
            "job_title": _preview(agent.job_title or ""),
        }
        candidate = _directory_page(
            [*items, item], offset=offset, limit=limit, has_more=len(agents) > len(items) + 1,
        )
        if len(candidate) > _DIRECTORY_PAGE_MAX_CHARS:
            break
        items.append(item)

    return _directory_page(items, offset=offset, limit=limit, has_more=len(agents) > len(items))


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
    lines.append(_message(lang, "profile_uri", value=f"galaris://agent/{agent.id}"))
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
        lang, "voice_calling", value=_boolean(lang, capabilities.voice_calling)
    ))
    lines.append(_message(
        lang, "file_tools", value=_boolean(lang, capabilities.file_tools)
    ))
    lines.append(_message(
        lang, "console_execution", value=_boolean(lang, capabilities.console_execution)
    ))

    return "\n".join(lines)
