"""Public, side-effect-free contracts used to benchmark agent decisions."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .briefing_service import (
    briefing_system_prompt,
    render_briefing_input,
    validate_briefing_resources,
)
from .contracts import BriefingChoice
from .planner_service import (
    Plan,
    built_in_planner_prompt,
    planner_evaluation_system_prompt,
    planner_prompt_base,
)


class PlannerLabConfiguration(BaseModel):
    """Dataset-owned Planner prompt, independent from runtime after creation."""

    model_config = ConfigDict(extra="forbid")

    schema_: Literal["galaris.planner-lab-configuration"] = Field(
        default="galaris.planner-lab-configuration",
        alias="schema",
        serialization_alias="schema",
    )
    system_prompt: str = Field(min_length=1, max_length=50_000)

    @field_validator("system_prompt")
    @classmethod
    def prompt_not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The Planner system prompt cannot be blank.")
        return value


async def default_planner_lab_configuration() -> PlannerLabConfiguration:
    return PlannerLabConfiguration(system_prompt=await planner_prompt_base())


def built_in_planner_lab_configuration() -> PlannerLabConfiguration:
    return PlannerLabConfiguration(system_prompt=built_in_planner_prompt())


async def resolve_planner_lab_configuration(value: object) -> PlannerLabConfiguration:
    if isinstance(value, dict) and value:
        return PlannerLabConfiguration.model_validate(value)
    return await default_planner_lab_configuration()


__all__ = [
    "BriefingChoice",
    "Plan",
    "PlannerLabConfiguration",
    "briefing_system_prompt",
    "render_briefing_input",
    "validate_briefing_resources",
    "built_in_planner_lab_configuration",
    "default_planner_lab_configuration",
    "planner_evaluation_system_prompt",
    "resolve_planner_lab_configuration",
]
