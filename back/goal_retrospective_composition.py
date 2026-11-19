"""Bind the weekly Goal to existing evidence and personal skill services."""

from uuid import UUID

from app.agent import register_agent_creation_initializer, register_agent_profile_observer
from app.document import redact_secrets
from app.dream import build_task_outcome_evidence, significance_reason
from app.goal import (
    RetrospectiveLearning, ensure_weekly_retrospective, register_retrospective_learning,
    weekly_retrospective_created,
)
from app.skill import (
    LearnedSkillDecision, LearnedSkillOperation, apply_learning_decision,
    learning_code_prefix, refresh_learned_skill_runtime,
)


async def read_evidence(agent_id: int, source_id: UUID) -> dict[str, object] | None:
    evidence = await build_task_outcome_evidence(source_id)
    if evidence is None or evidence.owner_agent_id != agent_id:
        return None
    eligible, reason = significance_reason(evidence)
    return {
        **evidence.model_dump(mode="json", exclude={"task_id", "owner_agent_id", "fingerprint",
                                                   "injected_memory_ids", "observations"}),
        "observations": [dict(item.model_dump(mode="json"), detail=item.detail[:500])
                         for item in evidence.observations],
        "task_uri": f"galaris://task/{source_id}",
        "learning_eligible": eligible,
        "signal": reason,
    }


async def apply_evidence(
    agent_id: int, source_id: UUID, proposal: dict[str, object],
) -> dict[str, object]:
    operation = LearnedSkillOperation.model_validate(proposal)
    for value in (operation.markdown, operation.rationale, operation.label):
        if redact_secrets(value) != value:
            raise ValueError("Redact sensitive information from the proposed skill change.")

    evidence = await build_task_outcome_evidence(source_id)
    if evidence is None or evidence.owner_agent_id != agent_id:
        raise PermissionError("The source Task evidence is unavailable.")
    eligible, reason = significance_reason(evidence)
    if not eligible:
        raise ValueError("The source Task has no verified learning signal.")
    observations = {item.reference: item for item in evidence.observations}
    if any(reference not in observations for reference in operation.evidence_refs):
        raise ValueError("Cite only references returned for the source Task.")
    cited = [observations[reference] for reference in operation.evidence_refs]
    if operation.action in {"CREATE", "REINFORCE"} and not any(
        (item.kind == "tool_result" and item.status == "success" and item.detail)
        or (item.kind == "human_followup" and reason == "explicit_human_validation")
        or (item.kind == "goal_judgement" and reason == "goal_validation")
        for item in cited
    ):
        raise ValueError("Creation or reinforcement requires a cited observed success or validation.")
    if operation.action == "WEAKEN" and not any(
        (item.kind == "human_followup" and reason == "explicit_human_correction")
        or (item.kind == "goal_judgement" and reason == "goal_refutation")
        or (item.kind in {"terminal_result", "attempt", "tool_result", "child_result"}
            and item.status.lower() in {"error", "retry", "blocked"}
            and reason in {"definitive_failure", "repeated_failure", "recovered_after_failure", "mixed_plan"})
        for item in cited
    ):
        raise ValueError("Weakening requires a cited observation that contradicts the procedure.")
    if operation.action == "REVISE" and operation.expected_revision is None:
        raise ValueError("Revising a skill requires the observed package revision.")

    weight = {
        "explicit_human_correction": 1.2, "explicit_human_validation": 1.0,
        "recovered_after_failure": 1.0, "guard_retry": 0.9, "verified_tool_success": 0.8,
        "mixed_plan": 0.7, "repeated_failure": 0.9, "definitive_failure": 0.8,
        "goal_validation": 1.0, "goal_refutation": 1.0,
    }.get(reason, 0.5)
    result = await apply_learning_decision(
        agent_id=agent_id, source_ref=f"galaris://task/{source_id}",
        source_fingerprint=evidence.fingerprint, allowed_evidence_refs=set(observations),
        evidence_weight=weight, decision=LearnedSkillDecision(operations=[operation]),
    )
    if result.refresh_required:
        await refresh_learned_skill_runtime(agent_id)
    return {"changed": result.changed, "source_task_uri": f"galaris://task/{source_id}"}


def register_weekly_retrospective() -> None:
    async def initialize(agent_id: int) -> None:
        await ensure_weekly_retrospective(agent_id)

    register_agent_creation_initializer("weekly-retrospective", initialize)
    register_agent_profile_observer("weekly-retrospective", weekly_retrospective_created)
    register_retrospective_learning(RetrospectiveLearning(read_evidence, apply_evidence, learning_code_prefix))
