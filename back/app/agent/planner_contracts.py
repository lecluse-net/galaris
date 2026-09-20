"""Validated planner output contracts and effect policies, independent of orchestration."""

from __future__ import annotations

import json
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from core.params import runtime_settings

FILE_PRODUCTION_TOOLS = frozenset(
    {
        "file_create",
        "file_write",
        "file_append",
        "file_edit",
        "file_copy",
        "file_move",
    }
)

FILE_DELIVERY_TOOLS = frozenset(
    {
        "file_copy",
        "messenger_room_send_file",
        "messenger_send_file_to_user",
    }
)

_DELIVERY_TOOLS = FILE_DELIVERY_TOOLS | frozenset(
    {
        "messenger_room_send_message",
        "messenger_send_message_to_user",
    }
)


class PlanBrief(BaseModel):
    """Self-contained mission brief used as the sole context for plan subtasks."""

    objective: str = Field(
        description="Semantic HTML fragment (paragraphs, lists, links; no images). Restate the request clearly, completely and unambiguously."
    )
    context: str = Field(
        default="",
        description=(
            "Every concrete piece of data needed for execution, copied verbatim from "
            "the conversation (URLs, identifiers, names, numbers, paths, exact wordings)."
        ),
    )
    strategy: str = Field(
        default="",
        description=(
            "Execution strategy: how the planner will approach and sequence the work, "
            "and why that approach is appropriate."
        ),
    )
    rationale: str = Field(
        default="",
        description=(
            "Short justification of the plan structure, decomposition level, tradeoffs "
            "and notable risks."
        ),
    )
    constraints: list[str] = Field(
        default_factory=lambda: [],
        description="Explicit constraints, guardrails and stated assumptions.",
    )
    success_criteria: list[str] = Field(
        default_factory=lambda: [],
        description="Verifiable criteria the final result must satisfy.",
    )
    deliverables: list[str] = Field(default_factory=lambda: [], description="Expected artifacts.")


class PlanStep(BaseModel):
    """One recursive plan step, represented as either a leaf or a group."""

    objective: str = Field(
        description="Semantic HTML fragment (paragraphs, lists, links; no images) with precise step instructions describing what must be done or produced."
    )
    label: str = Field(description="Short step title.")
    effort: Literal["standard", "high"] = Field(
        default="standard",
        description=(
            'Executor effort: "high" only for material cognitive complexity such as '
            "non-trivial judgment, synthesis, ambiguity, diagnosis or problem solving; "
            '"standard" for bounded mechanical execution, even with several tool calls or '
            "an explicitly authorized destructive side effect. Safety is not an effort tier."
        ),
    )
    tools: list[str] = Field(
        default_factory=lambda: [],
        description=(
            "Exact AVAILABLE_TOOLS identifiers needed by this step. Keep the list minimal; "
            "do not invent identifiers."
        ),
    )
    artifact_policy: Literal["none", "intermediate", "final"] = Field(
        default="none",
        description=(
            "Server-enforced artifact lifecycle. File-producing steps without delivery "
            "are intermediate; steps that deliver a file are final."
        ),
    )
    delivery_policy: Literal["forbidden", "required"] = Field(
        default="forbidden",
        description=(
            "Server-enforced delivery permission. Required only when an exact delivery "
            "tool is selected; otherwise delivery is forbidden."
        ),
    )
    steps: list["PlanStep"] = Field(
        default_factory=lambda: [],
        description=(
            "Ordered substeps when the work contains substantial independently verifiable "
            "components or benefits from durable implementation, refinement, and validation "
            "passes. A single artifact or target file may still require substeps. Leave empty "
            "only when the step is atomic and can be completed and verified as one coherent unit."
        ),
    )

    @model_validator(mode="after")
    def normalize_effect_policies(self) -> "PlanStep":
        """Derive safe policies from the exact tools selected by the planner."""

        selected = frozenset(self.tools)
        delivery_tools = selected & _DELIVERY_TOOLS
        file_delivery_tools = selected & FILE_DELIVERY_TOOLS
        produces_file = bool(selected & FILE_PRODUCTION_TOOLS)
        if delivery_tools:
            self.delivery_policy = "required"
        elif self.delivery_policy == "required":
            raise ValueError("delivery_policy=required needs an exact delivery tool")
        else:
            self.delivery_policy = "forbidden"

        if file_delivery_tools:
            self.artifact_policy = "final"
        elif produces_file:
            if self.artifact_policy == "final":
                raise ValueError("artifact_policy=final needs an exact file-delivery tool")
            self.artifact_policy = "intermediate"
        elif self.artifact_policy != "none":
            raise ValueError("an artifact policy needs a file production or delivery tool")
        return self


class Plan(BaseModel):
    """A mission brief and ordered step tree generated in one pass.

    Non-empty ``clarification_questions`` replace the plan until the user answers.
    """

    clarification_questions: list[str] = Field(
        default_factory=lambda: [],
        description=(
            "Questions to ask the user ONLY if essential information is missing. "
            "When set, leave `brief` and `steps` empty."
        ),
    )
    brief: Optional[PlanBrief] = Field(
        default=None,
        description="Mission brief — mandatory when steps are provided.",
    )
    steps: list[PlanStep] = Field(
        default_factory=lambda: [], description="Ordered root steps of the plan."
    )
    tool_catalog_version: str = Field(
        default="",
        description=(
            "Server-managed version of AVAILABLE_TOOLS. Leave empty; Galaris overwrites it."
        ),
    )

    @field_validator("brief", mode="before")
    @classmethod
    def parse_stringified_brief(cls, value: Any) -> Any:
        """Accept providers that serialize the nested object as JSON text."""
        if not isinstance(value, str):
            return value
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    @model_validator(mode="after")
    def bounded_tree(self) -> "Plan":
        """Reject a tree that could materialize an unreasonable number of tasks."""
        if self.clarification_questions:
            return self

        def counts(steps: list[PlanStep]) -> tuple[int, int]:
            nodes = 0
            leaves = 0
            for step in steps:
                nodes += 1
                if step.steps:
                    nested_nodes, nested_leaves = counts(step.steps)
                    nodes += nested_nodes
                    leaves += nested_leaves
                else:
                    leaves += 1
            return nodes, leaves

        nodes, leaves = counts(self.steps)
        if nodes > runtime_settings.TASK_PLAN_MAX_NODES:
            raise ValueError(
                f"Plan too large: {nodes} nodes; maximum is {runtime_settings.TASK_PLAN_MAX_NODES}."
            )
        if leaves > runtime_settings.TASK_PLAN_MAX_LEAVES:
            raise ValueError(
                f"Plan too large: {leaves} leaves; maximum is "
                f"{runtime_settings.TASK_PLAN_MAX_LEAVES}."
            )
        return self


class BlockedPlanRecovery(BaseModel):
    """One bounded planner decision after a leaf reports ``BLOCKED:``."""

    outcome: Literal["REPLAN", "FAIL"]
    rationale: str = Field(
        default="",
        description="Why a materially different recovery is safe, or why the plan must fail.",
    )
    steps: list[PlanStep] = Field(
        default_factory=lambda: [],
        description="Only the minimal actions needed to remove the blocker.",
    )

    @model_validator(mode="after")
    def valid_outcome(self) -> "BlockedPlanRecovery":
        if self.outcome == "REPLAN" and not self.steps:
            raise ValueError("REPLAN requires at least one recovery step.")
        if self.outcome == "FAIL" and self.steps:
            raise ValueError("FAIL must not contain executable recovery steps.")
        # Reuse the normal tree bounds for the proposed recovery fragment.
        Plan(steps=self.steps)
        return self


PlanStep.model_rebuild()

BlockedPlanRecovery.model_rebuild()
