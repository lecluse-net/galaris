"""Admit a documentation task for a saved REST Service."""

import json
import re
from html import escape
from urllib.parse import urlsplit
from uuid import UUID

from app.agent import AgentTaskDraft, installed_galaris_agent_id, submit_background_task
from core.i18n import render_prompt, tr
from core.user import get_current_user_id

from .models import Service


class GalarisAssistantUnavailable(LookupError):
    """The assistant from this installation is missing or archived."""


def _skill_code(service: Service) -> str:
    code = re.sub(r"[^a-z0-9]+", "-", service.code.lower()).strip("-")
    if code and code == service.code and len(code) <= 92:
        return f"service-{code}"
    # Preserve a stable, valid package name for legacy or non-slug Service codes.
    suffix = f"-{service.id}"
    prefix = f"service-{code or 'api'}"[:100 - len(suffix)].rstrip("-")
    return prefix + suffix


def _source_url(value: object, *, origin_only: bool = False) -> str:
    if not isinstance(value, str):
        return ""
    try:
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username is not None or url.password is not None:
            return ""
        return url._replace(path="" if origin_only else url.path, query="", fragment="").geturl()
    except ValueError:
        return ""


async def generate_service_skill(service: Service, operation_id: UUID) -> UUID:
    agent_id = await installed_galaris_agent_id()
    if agent_id is None:
        raise GalarisAssistantUnavailable

    skill_code = _skill_code(service)
    uri = f"galaris://skill/{skill_code}/SKILL.md"
    label = render_prompt(await tr("services.skill_generation.label"), label=service.label)
    demand = render_prompt(await tr("services.skill_generation.objective"), skill_code=skill_code, uri=uri)
    context = {"label": service.label, "service_code": service.code}
    if documentation := _source_url((service.catalog or {}).get("documentation")):
        context["documentation_url"] = documentation
    if api_origin := _source_url((service.rest_config or {}).get("base_url"), origin_only=True):
        context["api_origin"] = api_origin
    # Keep provider addresses and labels as JSON data without granting effects
    # on any URI mentioned in them. Task admission treats literal URIs as targets.
    source_context = json.dumps(context, ensure_ascii=False, indent=2).replace("://", r":\/\/")
    objective = demand + render_prompt(await tr("services.skill_generation.context"), context=escape(source_context))

    return await submit_background_task(AgentTaskDraft(
        label=label, objective=objective, agent_id=agent_id,
        idempotency_key=f"service-skill:{service.id}:{get_current_user_id()}:{operation_id}",
    ))
