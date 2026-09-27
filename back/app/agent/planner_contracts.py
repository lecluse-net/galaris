"""Validated planner output contracts and effect policies, independent of orchestration."""

from __future__ import annotations

import json
from typing import Any, Literal, Optional
from pydantic import BaseModel, Field, field_validator, model_validator
from core.params import runtime_settings

MAX_MECHANICAL_BATCH_ITEMS = 5

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


class PlanCollection(BaseModel):
    """A finite collection expanded by the server after a durable inventory."""

    inventory_objective: str = Field(
        min_length=1,
        description=(
            "HTML instructions to identify every remaining item from an existing inventory or "
            "authorized source. Discover identifiers only; never perform the item work here."
        ),
    )
    inventory_tools: list[str] = Field(
        min_length=1,
        description=(
            "Exact authorized tools for inventory discovery, including file_create and file_read. "
            "The server adds the JSON Dataset inventory format to the discovery task."
        ),
    )
    item_objective: str = Field(
        min_length=1,
        description=(
            "HTML instructions to complete and verify ONE item end to end, using the exact "
            "item inputs supplied by the server. Reuse existing outputs and record durable results."
        ),
    )

    @model_validator(mode="after")
    def requires_inventory_storage(self) -> "PlanCollection":
        if not {"file_create", "file_read"}.issubset(self.inventory_tools):
            raise ValueError("Collection discovery requires file_create and file_read")
        return self


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
    item_count: int | None = Field(
        default=1,
        ge=1,
        description=(
            "Number of independently verifiable items covered by this step; null if unknown. "
            "Substantial per-item work or large/unknown batches require substeps or collection. "
            f"A mechanical batch of at most {MAX_MECHANICAL_BATCH_ITEMS} known items may stay one leaf."
        ),
    )
    item_work: Literal["substantial", "mechanical"] = Field(
        default="substantial",
        description=(
            "Use mechanical only for trivial deterministic operations on known targets with "
            "a simple batch completion check, such as applying three supplied document names. "
            "Reading and transforming each document, judgment, or substantial per-item validation "
            "is substantial even with standard effort. This classification never changes routing."
        ),
    )
    collection: PlanCollection | None = Field(
        default=None,
        description=(
            "Use for repeated per-item work, especially when identifiers require discovery or "
            "the items exceed static plan limits. This step is a group, never an executor leaf. "
            "Its tools and effort apply to each item; leave steps empty."
        ),
    )

    @model_validator(mode="after")
    def normalize_effect_policies(self) -> "PlanStep":
        """Derive safe policies from the exact tools selected by the planner."""

        if self.collection is not None and self.steps:
            raise ValueError("A collection cannot also contain static substeps")
        small_mechanical_batch = (
            self.item_work == "mechanical"
            and self.item_count is not None
            and self.item_count <= MAX_MECHANICAL_BATCH_ITEMS
        )
        if (
            not self.steps
            and self.collection is None
            and self.item_count != 1
            and not small_mechanical_batch
        ):
            raise ValueError("Repeated or unbounded work needs substeps or a collection")

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

        def count_leaves(steps: list[PlanStep], depth: int = 1) -> int:
            leaves = 0
            for step in steps:
                if (
                    depth + (1 if step.collection is not None else 0)
                    > runtime_settings.TASK_PLAN_MAX_DEPTH
                ):
                    raise ValueError("Plan exceeds maximum depth; do not flatten work into a leaf")
                if step.steps:
                    leaves += count_leaves(step.steps, depth + 1)
                else:
                    leaves += 1
            return leaves

        leaves = count_leaves(self.steps)
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
