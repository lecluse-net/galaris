"""Bounded executor-owned milestones, separate from coordination and terminal outcomes."""
from __future__ import annotations

from typing import Any, Literal, Mapping
import json

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class WorkMilestone(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    key: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")
    label: str = Field(min_length=1, max_length=300)
    acceptance: str = Field(min_length=1, max_length=1000)
    state: Literal["pending", "doing", "done", "blocked"] = "pending"
    observation: str = Field(default="", max_length=1500)
    resource_refs: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def require_observed_outcomes(self) -> WorkMilestone:
        if self.state in {"done", "blocked"} and not self.observation.strip():
            raise ValueError("A completed or blocked milestone requires an observed result")
        if any("://" not in ref or len(ref) > 2000 for ref in self.resource_refs):
            raise ValueError("Milestone resources must use bounded canonical URIs")
        return self


class WorkPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["galaris.work-plan/v1"] = "galaris.work-plan/v1"
    milestones: list[WorkMilestone] = Field(min_length=1, max_length=20)
    next_action: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def validate_progress(self) -> WorkPlan:
        if len({item.key for item in self.milestones}) != len(self.milestones):
            raise ValueError("Milestone keys must be unique")
        if sum(item.state == "doing" for item in self.milestones) > 1:
            raise ValueError("An executor has at most one current milestone")
        if any(item.state != "done" for item in self.milestones) and not self.next_action.strip():
            raise ValueError("Unfinished work must retain its next action")
        if len(json.dumps(self.model_dump(mode="json"), ensure_ascii=False)) > 20_000:
            raise ValueError("Work tracking exceeds its bounded context budget")
        return self


def work_plan_progress(data: Mapping[str, Any]) -> dict[str, Any] | None:
    """Expose declared milestone progress without changing the Task outcome."""
    raw = data.get("work_plan")
    if not isinstance(raw, dict):
        return None
    try:
        plan = WorkPlan.model_validate(raw)
    except ValidationError:
        # Tracking is an optional projection; older readers must still expose the Task.
        return None
    done = sum(item.state == "done" for item in plan.milestones)
    current = next((item.label for item in plan.milestones if item.state in {"doing", "blocked"}), None)
    return {"done": done, "total": len(plan.milestones),
            "percent": round(100 * done / len(plan.milestones)),
            "current": current, "next_action": plan.next_action, "kind": "milestones"}
