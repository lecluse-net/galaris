"""Deterministic directives understood before conversation model dispatch."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, cast


ChatDirective = Literal[
    "task",
    "exec",
    "plan",
    "briefing",
    "standard",
    "high",
    "effort",
    "approve",
]
DirectTaskError = Literal[
    "missing_objective",
    "conflicting_route",
    "conflicting_effort",
]
ForcedRoute = Literal["EXEC", "BRIEFING", "PLAN"]
ForcedEffort = Literal["standard", "high"]

_DIRECTIVE_RE = re.compile(
    r"(?<!\w)@(?P<tag>task|exec|plan|briefing|standard|high|effort|approve)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DirectTaskDirective:
    """A direct Task request parsed without consulting a language model."""

    objective: str
    forced_route: ForcedRoute | None = None
    forced_effort: ForcedEffort | None = None
    briefing_requested: bool = False
    auto_approve: bool = False
    error: DirectTaskError | None = None


def available_chat_directives(agent_driver: str) -> tuple[ChatDirective, ...]:
    """Expose only directives that make sense for the selected Task driver."""

    common: tuple[ChatDirective, ...] = (
        "task",
        "standard",
        "high",
        "effort",
        "approve",
    )
    if agent_driver.strip().casefold() != "internal":
        return common
    return (
        "task",
        "exec",
        "plan",
        "standard",
        "high",
        "effort",
        "approve",
    )


async def get_agent_chat_directives(
    agent_id: int,
) -> tuple[ChatDirective, ...] | None:
    """Resolve a command catalog through the conversation domain's public surface."""

    from app.agent import get_agent_record

    agent = await get_agent_record(agent_id)
    if agent is None:
        return None
    return available_chat_directives(agent.agent_driver)


def parse_direct_task_directive(
    value: str,
    *,
    task_requested: bool = False,
) -> DirectTaskDirective | None:
    """Parse a direct Task requested by metadata, ``@task``, ``@plan`` or ``@effort``."""

    tags = [
        cast(ChatDirective, match.group("tag").casefold())
        for match in _DIRECTIVE_RE.finditer(value)
    ]

    if not ({"task", "plan", "effort"} & set(tags)) and not task_requested:
        return None

    objective = re.sub(r"[ \t]+", " ", _DIRECTIVE_RE.sub("", value)).strip()
    routes = {tag for tag in tags if tag in {"exec", "plan", "briefing"}}
    efforts = {tag for tag in tags if tag in {"standard", "high"}}
    if len(routes) > 1:
        return DirectTaskDirective(objective=objective, error="conflicting_route")
    if len(efforts) > 1:
        return DirectTaskDirective(objective=objective, error="conflicting_effort")
    if routes & {"plan", "briefing"} and "standard" in efforts:
        return DirectTaskDirective(objective=objective, error="conflicting_effort")
    if not objective:
        return DirectTaskDirective(objective="", error="missing_objective")

    route = next(iter(routes), None)
    effort = next(iter(efforts), None)
    forced_route: ForcedRoute | None = None
    if route == "exec":
        forced_route = "EXEC"
    elif route == "plan":
        forced_route = "PLAN"
    elif route == "briefing":
        forced_route = "BRIEFING"
    forced_effort: ForcedEffort | None = None
    if effort == "standard":
        forced_effort = "standard"
    elif effort == "high":
        forced_effort = "high"
    if route in {"plan", "briefing"}:
        forced_effort = "high"
    return DirectTaskDirective(
        objective=objective,
        forced_route=forced_route,
        forced_effort=forced_effort,
        briefing_requested=route == "briefing",
        auto_approve="approve" in tags,
    )


__all__ = [
    "ChatDirective",
    "DirectTaskDirective",
    "available_chat_directives",
    "get_agent_chat_directives",
    "parse_direct_task_directive",
]
