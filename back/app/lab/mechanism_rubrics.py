"""Versioned semantic rubrics for side-effect-free Lab mechanism benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schemas import EvaluationMechanism


@dataclass(frozen=True)
class RubricDimension:
    """One independently scored, observable quality dimension."""

    code: str
    label: str
    weight: int
    criteria: str

    def prompt_value(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "label": self.label,
            "weight_percent": self.weight,
            "criteria": self.criteria,
        }


@dataclass(frozen=True)
class MechanismRubric:
    """Stable scoring contract for one mechanism."""

    mechanism: EvaluationMechanism
    version: str
    dimensions: tuple[RubricDimension, ...]
    critical_failure_cap_percent: float = 50.0

    @classmethod
    def from_snapshot(
        cls, mechanism: EvaluationMechanism, value: dict[str, Any]
    ) -> "MechanismRubric":
        return cls(
            mechanism=mechanism,
            version=str(value["version"]),
            critical_failure_cap_percent=float(value["critical_failure_cap_percent"]),
            dimensions=tuple(
                RubricDimension(
                    code=str(item["code"]),
                    label=str(item["label"]),
                    weight=int(item["weight_percent"]),
                    criteria=str(item["criteria"]),
                )
                for item in value["dimensions"]
            ),
        )

    def __post_init__(self) -> None:
        if sum(item.weight for item in self.dimensions) != 100:
            raise ValueError(f"Rubric weights must total 100 for {self.mechanism}")
        if len({item.code for item in self.dimensions}) != len(self.dimensions):
            raise ValueError(f"Rubric dimension codes must be unique for {self.mechanism}")

    def prompt_value(self) -> dict[str, object]:
        return {
            "version": self.version,
            "critical_failure_cap_percent": self.critical_failure_cap_percent,
            "dimensions": [item.prompt_value() for item in self.dimensions],
        }


def _dimension(code: str, label: str, weight: int, criteria: str) -> RubricDimension:
    return RubricDimension(code=code, label=label, weight=weight, criteria=criteria)


_RUBRICS: dict[EvaluationMechanism, MechanismRubric] = {
    "task_analysis": MechanismRubric(
        mechanism="task_analysis",
        version="task-analysis-score:v1",
        dimensions=(
            _dimension(
                "evidence_grounding",
                "Evidence grounding",
                40,
                "Every finding is supported by the supplied execution dossier and separates observation from hypothesis.",
            ),
            _dimension(
                "diagnostic_accuracy",
                "Diagnostic accuracy",
                30,
                "Identifies actual failures, success and uncertainty with an appropriate verdict.",
            ),
            _dimension(
                "actionability",
                "Actionability",
                20,
                "Recommendations address evidenced causes and can be verified.",
            ),
            _dimension(
                "coverage",
                "Coverage",
                10,
                "Acknowledges missing or truncated evidence and covers material events.",
            ),
        ),
    ),
    "dispatcher": MechanismRubric(
        mechanism="dispatcher",
        version="dispatcher-score:v3",
        dimensions=(
            _dimension(
                "route",
                "Route",
                60,
                "Chooses an allowed route appropriate to the request and pipeline policy.",
            ),
            _dimension(
                "effort",
                "Effort",
                20,
                "Selects effort appropriate to complexity and explicit constraints.",
            ),
            _dimension(
                "language", "Language", 5, "Respects the language of the request and context."
            ),
            _dimension(
                "reasoning",
                "Justification",
                15,
                "Grounds the decision in supplied evidence and obeys forced routing constraints.",
            ),
        ),
    ),
    "briefing": MechanismRubric(
        mechanism="briefing",
        version="briefing-score:v2",
        dimensions=(
            _dimension(
                "objective_fidelity",
                "Objective fidelity",
                25,
                "Preserves the real objective, requested deliverable and relevant context without changing their meaning.",
            ),
            _dimension(
                "constraint_coverage",
                "Constraint coverage",
                20,
                "Covers material user constraints, risks and prohibitions; omissions are weighted by operational impact.",
            ),
            _dimension(
                "actionability",
                "Actionability",
                20,
                "Provides a concise execution approach that another agent can follow on its first attempt.",
            ),
            _dimension(
                "resource_relevance",
                "Resource relevance",
                20,
                "Selects available resources that are necessary or well justified. Compare identifiers as a set; ordering, labels and optional confidence scores are not normative.",
            ),
            _dimension(
                "verification_quality",
                "Verification quality",
                15,
                "Defines completion checks that can demonstrate the requested outcome instead of merely asserting success.",
            ),
        ),
    ),
    "planner": MechanismRubric(
        mechanism="planner",
        version="planner-score:v2",
        dimensions=(
            _dimension(
                "objective_fidelity",
                "Objective fidelity",
                20,
                "Keeps the plan aligned with the objective, context, constraints and requested deliverables.",
            ),
            _dimension(
                "decomposition_coverage",
                "Decomposition and coverage",
                25,
                "Breaks the work into sufficient, coherent steps without omitting material work or adding unrelated scope.",
            ),
            _dimension(
                "feasibility_dependencies",
                "Feasibility and dependencies",
                20,
                "Orders dependencies correctly and proposes steps that are executable with the stated context and capabilities.",
            ),
            _dimension(
                "resource_strategy",
                "Resource strategy",
                15,
                "Uses available tools and resources appropriately. Alternative valid tool selections and step orderings are allowed when justified.",
            ),
            _dimension(
                "verification_deliverables",
                "Verification and deliverables",
                20,
                "Defines concrete success criteria and deliverables that establish completion of the objective.",
            ),
        ),
    ),
    "topic_classification": MechanismRubric(
        mechanism="topic_classification",
        version="topic_detection-sequence-score:v3",
        dimensions=(
            _dimension(
                "per_message_accuracy",
                "Per-message Topic accuracy",
                35,
                "Assigns a relevant durable Topic to every message in the exchange, without skipping, shifting or reordering messages.",
            ),
            _dimension(
                "sequence_continuity",
                "Sequential continuity",
                25,
                "Keeps replies, corrections and same-subject developments together while carrying the previous decision forward message by message.",
            ),
            _dimension(
                "topic_boundaries",
                "Topic boundaries",
                20,
                "Detects genuine subject changes at the correct message and can return to an earlier Topic in an A-B-A sequence.",
            ),
            _dimension(
                "temporal_reasoning",
                "Temporal reasoning",
                10,
                "Uses elapsed time and local cadence as weak revisable evidence, without turning a pause or immediate succession into a hard semantic boundary.",
            ),
            _dimension(
                "topic_naming",
                "Topic naming quality",
                10,
                "Uses concise, readable and stable Topic names that represent the exchange content rather than transient phrasing.",
            ),
        ),
    ),
    "memory_extraction": MechanismRubric(
        mechanism="memory_extraction",
        version="memory_extraction-score",
        dimensions=(
            _dimension(
                "decision_correctness",
                "CREATE, LINK or IGNORE",
                30,
                "Chooses abstention, creation, or provenance linking consistently with the durable evidence and supplied existing memories.",
            ),
            _dimension(
                "evidence_grounding",
                "Evidence grounding",
                25,
                "Every created memory is explicitly supported by the source; invented or overgeneralized facts are heavily penalized.",
            ),
            _dimension(
                "link_precision",
                "LINK precision",
                20,
                "Links only to an existing memory that covers the same durable fact and exact social identity. A false link is a critical failure.",
            ),
            _dimension(
                "durability_coverage",
                "Durability and coverage",
                15,
                "Keeps important reusable facts while rejecting transient execution detail and one-off content.",
            ),
            _dimension(
                "retrieval_quality",
                "Existing-memory retrieval",
                10,
                "Ranks the existing memories needed for correct LINK or CREATE decisions near the top of the dataset corpus.",
            ),
        ),
    ),
    "outcome_reflection": MechanismRubric(
        mechanism="outcome_reflection",
        version="outcome_reflection-score:v2",
        dimensions=(
            _dimension(
                "evidence_grounding",
                "Evidence grounding",
                30,
                "Derives lessons only from observable outcome evidence and distinguishes facts from inference.",
            ),
            _dimension(
                "causal_caution",
                "Causal caution",
                20,
                "Avoids claiming causes, success or failure that the bounded evidence cannot establish.",
            ),
            _dimension(
                "lesson_relevance",
                "Lesson relevance",
                20,
                "Produces reusable lessons that address the observed outcome rather than generic advice.",
            ),
            _dimension(
                "actionability",
                "Actionability",
                15,
                "Makes future behavior or verification measurably better without prescribing unsupported actions.",
            ),
            _dimension(
                "coverage_precision",
                "Coverage and precision",
                15,
                "Covers material strengths, failures and uncertainty concisely without duplication or irrelevant commentary.",
            ),
        ),
    ),
    "goal_tracking": MechanismRubric(
        mechanism="goal_tracking",
        version="goal_tracking-score:v2",
        dimensions=(
            _dimension(
                "objective_alignment",
                "Objective alignment",
                20,
                "Keeps durable tracking and the continuation decision aligned with the long-running goal.",
            ),
            _dimension(
                "evidence_grounded_progress",
                "Evidence-grounded progress",
                25,
                "Updates progress only from the latest task evidence and does not convert claims into verified accomplishments.",
            ),
            _dimension(
                "continuation_decision",
                "Continuation decision",
                20,
                "Chooses CONTINUE or STOP consistently with remaining work, evidence, blockers and completion criteria.",
            ),
            _dimension(
                "tracking_continuity",
                "Tracking continuity",
                20,
                "Maintains a coherent durable Markdown state that preserves relevant prior context while incorporating the new cycle.",
            ),
            _dimension(
                "next_step_utility",
                "Next-step utility",
                15,
                "Makes the remaining work, uncertainty and next useful action clear enough to guide another cycle.",
            ),
        ),
    ),
    "task_executor": MechanismRubric(
        mechanism="task_executor",
        version="task_executor-score:v2",
        dimensions=(
            _dimension(
                "action_selection",
                "Action selection",
                30,
                "Chooses a tool-backed action, clarification, or direct reply consistently with the request and Task executor policy.",
            ),
            _dimension(
                "objective_fidelity",
                "Objective fidelity",
                25,
                "Preserves the requested outcome and material constraints in the recorded tool arguments and response.",
            ),
            _dimension(
                "tool_use_quality",
                "Tool-use quality",
                20,
                "Uses the effect-free Task tool recorder when action is required and avoids unsupported claims of completion.",
            ),
            _dimension(
                "response_quality",
                "Response quality",
                15,
                "Produces a useful, honest final response consistent with the recorded calls.",
            ),
            _dimension(
                "safety_clarification",
                "Safety and clarification",
                10,
                "Asks only necessary questions and avoids risky guesses or fabricated effects.",
            ),
        ),
    ),
    "conversation_executor": MechanismRubric(
        mechanism="conversation_executor",
        version="conversation_executor-score:v2",
        dimensions=(
            _dimension(
                "action_selection",
                "Action selection",
                35,
                "Correctly replies, clarifies, reads status, starts a Process, or starts a background Task for the requested scope.",
            ),
            _dimension(
                "objective_fidelity",
                "Objective fidelity",
                25,
                "The submitted Task objective or Process input preserves the user's requested outcome and constraints.",
            ),
            _dimension(
                "tool_use_quality",
                "Tool-use quality",
                20,
                "Uses only the bounded conversation tools and never claims an unrecorded effect.",
            ),
            _dimension(
                "response_quality",
                "Response quality",
                15,
                "Keeps the conversational acknowledgement concise, natural and useful without exposing internal identifiers unnecessarily.",
            ),
            _dimension(
                "safety_clarification",
                "Safety and clarification",
                5,
                "Clarifies material ambiguity and does not launch work for a request that only needs conversation.",
            ),
        ),
    ),
    "voice_executor": MechanismRubric(
        mechanism="voice_executor",
        version="voice_executor-score:v2",
        dimensions=(
            _dimension(
                "action_selection",
                "Action selection",
                35,
                "Correctly speaks, clarifies, reads status, starts a Process, or starts a background Task for the requested scope.",
            ),
            _dimension(
                "objective_fidelity",
                "Objective fidelity",
                25,
                "The submitted Task objective or Process input preserves the spoken user's requested outcome and constraints.",
            ),
            _dimension(
                "tool_use_quality",
                "Tool-use quality",
                20,
                "Uses only the bounded voice-conversation tools and never claims an unrecorded effect.",
            ),
            _dimension(
                "response_quality",
                "Spoken response quality",
                15,
                "Produces a concise, natural response suitable for speech without Markdown or technical receipts.",
            ),
            _dimension(
                "safety_clarification",
                "Safety and clarification",
                5,
                "Clarifies material ambiguity and avoids unsafe assumptions during the live call.",
            ),
        ),
    ),
}


def get_rubric(mechanism: EvaluationMechanism) -> MechanismRubric:
    """Return the immutable current semantic rubric for a mechanism."""

    return _RUBRICS[mechanism]


def list_rubrics() -> tuple[MechanismRubric, ...]:
    """Expose rubrics in registry order for tests and documentation helpers."""

    return tuple(_RUBRICS.values())
