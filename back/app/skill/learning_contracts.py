"""Public contracts for evidence-based, agent-scoped learned skills."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


LearnedSkillAction = Literal["CREATE", "REINFORCE", "REVISE", "WEAKEN"]
LearnedSkillRuntimeRefresher = Callable[[int], Awaitable[None]]


_runtime_refresher: LearnedSkillRuntimeRefresher | None = None


def register_learned_skill_runtime_refresher(
    refresher: LearnedSkillRuntimeRefresher,
) -> None:
    """Register the composition-owned hook for external runtime projections."""

    global _runtime_refresher
    _runtime_refresher = refresher


async def refresh_learned_skill_runtime(agent_id: int) -> None:
    """Refresh the external projection when the composition provides a hook."""

    if _runtime_refresher is not None:
        await _runtime_refresher(agent_id)


class LearnedSkillContext(BaseModel):
    id: UUID
    code: str
    label: str
    description: str
    markdown: str
    revision: int
    score: float
    evidence_count: int
    injectable: bool


class LearnedSkillOperation(BaseModel):
    action: LearnedSkillAction
    target_skill_id: UUID | None = None
    code: str = Field(default="", max_length=100)
    label: str = Field(default="", max_length=255)
    markdown: str = Field(default="", max_length=16_000)
    evidence_refs: list[str] = Field(min_length=1, max_length=12)
    rationale: str = Field(min_length=1, max_length=1_200)
    confidence: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_shape(self) -> "LearnedSkillOperation":
        if self.action == "CREATE":
            if self.target_skill_id is not None or not self.code or not self.label or not self.markdown:
                raise ValueError("CREATE requires code, label and markdown, without target_skill_id")
        elif self.target_skill_id is None:
            raise ValueError(f"{self.action} requires target_skill_id")
        if self.action == "REVISE" and not self.markdown:
            raise ValueError("REVISE requires complete markdown")
        if self.action in {"REINFORCE", "WEAKEN"} and self.markdown:
            raise ValueError(f"{self.action} must not replace skill instructions")
        return self


class LearnedSkillDecision(BaseModel):
    operations: list[LearnedSkillOperation] = Field(
        default_factory=lambda: list[LearnedSkillOperation](),
        max_length=3,
    )


@dataclass(frozen=True, slots=True)
class LearnedSkillApplyResult:
    changed: int
    refresh_required: bool


__all__ = [
    "LearnedSkillAction",
    "LearnedSkillApplyResult",
    "LearnedSkillContext",
    "LearnedSkillDecision",
    "LearnedSkillOperation",
    "LearnedSkillRuntimeRefresher",
    "refresh_learned_skill_runtime",
    "register_learned_skill_runtime_refresher",
]
