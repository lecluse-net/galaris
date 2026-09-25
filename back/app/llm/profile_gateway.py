"""Exact public profile selectors, shared by the protocol gateways."""

from dataclasses import dataclass
from typing import Literal

from fastapi import Request
from sqlalchemy import select

from core.database import get_db
from core.i18n import render_prompt, tr
from . import llm_service, model_usages
from .profile_models import LlmProfile
from .provider_models import LLM
from .provider_facade import ReasoningEffort
from .reasoning import normalize_reasoning_effort
from .schemas import ProxyModel


ProfileCapability = Literal["chat", "embedding", "decision"]
USAGES: dict[str, tuple[str, ProfileCapability]] = {
    "text/ultra-low": (model_usages.TEXT_ULTRA_LOW, "chat"),
    "text/low": (model_usages.TEXT_LOW, "chat"),
    "text/standard": (model_usages.TEXT_STANDARD, "chat"),
    "text/default": (model_usages.TEXT_STANDARD, "chat"),
    "text/high": (model_usages.TEXT_HIGH, "chat"),
    "embedding/default": (model_usages.VECTOR, "embedding"),
    "decision/default": (model_usages.DECISION, "decision"),
}


async def mark_profile_api(request: Request) -> None:
    request.state.llm_profile_api = True


def is_profile_api(request: Request) -> bool:
    return getattr(request.state, "llm_profile_api", False) is True


async def profile_error(key: str, *, model: str = "") -> str:
    return render_prompt(await tr(f"llm_api.errors.{key}"), model=model)


@dataclass(frozen=True)
class ProfileSelection:
    selector: str
    profile: LlmProfile
    field: str
    llm: LLM
    reasoning_effort: ReasoningEffort | None


def supports(llm: LLM, capability: ProfileCapability) -> bool:
    return llm.provider.is_active and capability in {
        llm.primary_capability, *(llm.service_capabilities or []),
    }


async def resolve_profile_model(value: object, capability: ProfileCapability) -> ProfileSelection:
    selector = str(value or "")
    parts = selector.split("/")
    usage = USAGES.get("/".join(parts[1:])) if len(parts) == 3 else None
    if usage is None or usage[1] != capability:
        raise ValueError(await profile_error("profile_selector_invalid", model=selector))
    profile = await get_db().scalar(select(LlmProfile).where(LlmProfile.code == parts[0]))
    if profile is None:
        raise LookupError(await profile_error("profile_selector_unavailable", model=selector))
    field = usage[0]
    llm_id: int | None = getattr(profile, field)
    llm = await llm_service.get_llm(llm_id) if llm_id is not None else None
    if llm is None or not supports(llm, capability):
        raise LookupError(await profile_error("profile_selector_unavailable", model=selector))
    reasoning_field = model_usages.reasoning_field_for_text_tier(field)
    effort = normalize_reasoning_effort(getattr(profile, reasoning_field)) if reasoning_field else None
    return ProfileSelection(selector, profile, field, llm, effort)


async def profile_models(capabilities: tuple[ProfileCapability, ...]) -> list[ProxyModel]:
    profiles = (await get_db().scalars(select(LlmProfile).order_by(LlmProfile.code))).all()
    llms = {llm.id: llm for llm in await llm_service.list_llms()}
    result: list[ProxyModel] = []
    for profile in profiles:
        for usage, (field, capability) in USAGES.items():
            llm = llms.get(getattr(profile, field))
            if capability in capabilities and llm is not None and supports(llm, capability):
                result.append(ProxyModel(id=f"{profile.code}/{usage}", context_length=llm.context_length))
    return result
