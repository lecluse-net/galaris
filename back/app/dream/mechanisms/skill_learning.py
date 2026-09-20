"""Learn and reinforce reusable agent skills from deterministic Task evidence."""

from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, select
from sqlalchemy.sql import exists

from app.llm import LLMCallPurpose, llm_service, model_usages, run_prompted
from app.skill import (
    LearnedSkillDecision,
    LearnedSkillOperation,
    apply_learning_decision,
    learning_code_prefix,
    list_learning_context,
    refresh_learned_skill_runtime,
)
from app.skill import storage as skill_storage
from app.task import Task, TaskStatus
from core.database import get_db, get_db_session
from core.params import runtime_settings

from ..contracts import (
    DreamClaim,
    DreamPrepared,
    SignificanceReason,
    TaskOutcomeEvidence,
)
from ..language import output_language_instruction, source_language
from ..models import DreamReceipt
from ..outcome_evidence import build_task_outcome_evidence, significance_reason
from ..service import (
    claim_observed_for_learning,
    claim_retry,
    create_running_receipt,
    replace_prepared_payload,
)


_SCAN_BATCH = 100
_NEGATIVE_REASONS: frozenset[SignificanceReason] = frozenset(
    {
        "explicit_human_correction",
        "repeated_failure",
        "definitive_failure",
        "goal_refutation",
        "guard_retry",
    }
)
_SYSTEM_PROMPT = """
You maintain concise reusable SKILL.md procedures for one agent from bounded, observable Task
evidence. These skills are executable guidance, not memories or Task summaries.

Return at most three operations:
- CREATE a narrowly named candidate only when the evidence establishes reusable future procedure.
- REINFORCE an existing skill when the evidence independently supports its current instructions.
- REVISE an existing skill when the evidence supports a concrete correction or tighter scope.
- WEAKEN only when supplied evidence directly contradicts the current instructions.
- Return no operation for transient facts, one-off deliverables, public research findings,
  unverified claims, secrets, private reasoning, or evidence too weak to change future behavior.

Every operation must cite only supplied evidence references. CREATE codes must use the exact
required prefix. CREATE and REVISE return a complete SKILL.md whose YAML frontmatter contains only
name and description. Keep discovery precise: the description must say what the skill does and
when it applies. Keep instructions short, actionable, scoped to the evidence, and free of generic
advice. Prefer REINFORCE or REVISE when an existing candidate describes the same recurring action;
do not create a synonym or near-duplicate. A CREATE remains non-injectable until distinct Tasks
reinforce it enough times for the server's configured threshold. Do not invent files, tools,
permissions, outcomes, or facts. REINFORCE and WEAKEN never replace Markdown. Never update an
unknown skill identifier.
""".strip()


class SkillLearningPrepared(BaseModel):
    evidence: TaskOutcomeEvidence
    significance_reason: SignificanceReason
    included: bool
    decision: LearnedSkillDecision = Field(default_factory=LearnedSkillDecision)
    application_mode: Literal["observe", "learn"] = "observe"


def _evidence_weight(reason: SignificanceReason) -> float:
    return {
        "explicit_human_correction": 1.2,
        "explicit_human_validation": 1.0,
        "recovered_after_failure": 1.0,
        "guard_retry": 0.9,
        "verified_tool_success": 0.8,
        "mixed_plan": 0.7,
        "repeated_failure": 0.9,
        "definitive_failure": 0.8,
        "goal_validation": 1.0,
        "goal_refutation": 1.0,
    }.get(reason, 0.5)


def _validated_decision(
    decision: LearnedSkillDecision,
    evidence: TaskOutcomeEvidence,
    existing: dict[UUID, tuple[str, str]],
    required_prefix: str,
    reason: SignificanceReason,
) -> LearnedSkillDecision:
    allowed_refs = {item.reference for item in evidence.observations}
    accepted: list[LearnedSkillOperation] = []
    touched: set[UUID] = set()
    created_codes: set[str] = set()
    for operation in decision.operations:
        refs = list(dict.fromkeys(operation.evidence_refs))
        if not refs or any(ref not in allowed_refs for ref in refs):
            continue
        if operation.action == "CREATE":
            try:
                code = skill_storage.validate_code(operation.code)
                if (
                    not code.startswith(required_prefix)
                    or code in created_codes
                    or not operation.label.strip()
                ):
                    continue
                skill_storage.metadata_from_markdown(
                    operation.markdown,
                    expected_code=code,
                )
            except ValueError:
                continue
            created_codes.add(code)
        else:
            target_id = operation.target_skill_id
            if target_id is None or target_id not in existing or target_id in touched:
                continue
            if operation.action == "WEAKEN" and reason not in _NEGATIVE_REASONS:
                continue
            if operation.action == "REVISE":
                try:
                    skill_storage.metadata_from_markdown(
                        operation.markdown,
                        expected_code=existing[target_id][0],
                    )
                except ValueError:
                    continue
            touched.add(target_id)
        accepted.append(operation.model_copy(update={"evidence_refs": refs}))
    return LearnedSkillDecision(operations=accepted)


class SkillLearningMechanism:
    key = "skill.learn_task_outcome"

    def __init__(self) -> None:
        self._late_scan_offset = 0

    async def is_available(self) -> bool:
        if runtime_settings.DREAM_SKILL_LEARNING_MODE == "off":
            return False
        async with get_db_session():
            from app.llm import profile_service

            return await profile_service.has_any_profile_value(model_usages.DREAM)

    def _already_considered(self) -> Any:
        return exists(
            select(DreamReceipt.id).where(
                DreamReceipt.mechanism_key == self.key,
                DreamReceipt.subject_kind == "task_skill_learning",
                DreamReceipt.subject_id.like(func.concat(cast(Task.id, String), ":%")),
            )
        )

    async def count_pending(self) -> int:
        if runtime_settings.DREAM_SKILL_LEARNING_MODE == "off":
            return 0
        async with get_db_session():
            return int(
                await get_db().scalar(
                    select(func.count(Task.id)).where(
                        Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                        ~self._already_considered(),
                    )
                )
                or 0
            )

    async def claim_one(self) -> DreamClaim | None:
        retry = await claim_retry(self.key)
        if retry is not None:
            return retry
        if runtime_settings.DREAM_SKILL_LEARNING_MODE == "learn":
            observed = await claim_observed_for_learning(
                self.key,
                subject_kind="task_skill_learning",
            )
            if observed is not None:
                return observed

        async with get_db_session():
            task_id = await get_db().scalar(
                select(Task.id)
                .where(
                    Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                    ~self._already_considered(),
                )
                .order_by(Task.created_at, Task.id)
                .limit(1)
            )
            if task_id is not None:
                return await self._claim_evidence(task_id)

            task_ids = list(
                (
                    await get_db().scalars(
                        select(Task.id)
                        .where(
                            Task.status.in_((TaskStatus.SUCCESS, TaskStatus.ERROR)),
                        )
                        .order_by(Task.created_at.desc(), Task.id.desc())
                        .offset(self._late_scan_offset)
                        .limit(_SCAN_BATCH)
                    )
                ).all()
            )
            self._late_scan_offset = (
                self._late_scan_offset + len(task_ids) if len(task_ids) == _SCAN_BATCH else 0
            )
            for candidate_id in task_ids:
                claim = await self._claim_evidence(candidate_id)
                if claim is not None:
                    return claim
        return None

    async def _claim_evidence(self, task_id: UUID) -> DreamClaim | None:
        evidence = await build_task_outcome_evidence(task_id)
        if evidence is None:
            return None
        subject_id = f"{task_id}:{evidence.fingerprint}"
        existing = await get_db().scalar(
            select(DreamReceipt.id).where(
                DreamReceipt.mechanism_key == self.key,
                DreamReceipt.subject_kind == "task_skill_learning",
                DreamReceipt.subject_id == subject_id,
            )
        )
        if existing is not None:
            return None
        claim = create_running_receipt(
            mechanism_key=self.key,
            subject_kind="task_skill_learning",
            subject_id=subject_id,
            prepared_payload={
                "_dream_stage": "evidence",
                "evidence": evidence.model_dump(mode="json"),
            },
        )
        await get_db().flush()
        return claim

    async def prepare(self, claim: DreamClaim) -> DreamPrepared:
        checkpoint = claim.prepared_payload or {}
        evidence = TaskOutcomeEvidence.model_validate(checkpoint.get("evidence"))
        included, reason = significance_reason(evidence)
        if not included or evidence.owner_agent_id is None:
            prepared = SkillLearningPrepared(
                evidence=evidence,
                significance_reason=reason,
                included=False,
            )
            return DreamPrepared(payload=prepared.model_dump(mode="json"))

        async with get_db_session():
            llm = await llm_service.get_profile_llm_for_agent_id(
                model_usages.DREAM,
                evidence.owner_agent_id,
            )
            if llm is None:
                raise RuntimeError("No Dream model or agent is available for skill learning.")
            learned = await list_learning_context(evidence.owner_agent_id)
            required_prefix = await learning_code_prefix(evidence.owner_agent_id)
            prompt_evidence = evidence.model_dump(mode="json")
            prompt_task_id = prompt_evidence.pop("task_id")
            prompt_evidence["task_uri"] = f"galaris://task/{prompt_task_id}"
            prompt = {
                "required_create_code_prefix": required_prefix,
                "task_evidence": prompt_evidence,
                "existing_learned_skills": [
                    {
                        **item.model_dump(mode="json", exclude={"markdown"}),
                        "markdown": item.markdown[:8_000],
                    }
                    for item in learned
                ],
            }
            language = source_language(evidence.language)
            inference = await run_prompted(
                llm=llm,
                output_type=LearnedSkillDecision,
                prompt=json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
                system_prompt=(
                    f"{_SYSTEM_PROMPT}\n\n"
                    f"{output_language_instruction(language, fields='labels, descriptions, rationales and Markdown instructions')}"
                ),
                task_id=evidence.task_id,
                agent_id=evidence.owner_agent_id,
                temperature=0.0,
                request_limit=None,
                output_retries=1,
                purpose=LLMCallPurpose.DREAM_SKILL_LEARNING,
                model_field=model_usages.DREAM,
            )
            existing = {item.id: (item.code, item.markdown) for item in learned}
            decision = _validated_decision(
                inference.output,
                evidence,
                existing,
                required_prefix,
                reason,
            )
            prepared = SkillLearningPrepared(
                evidence=evidence,
                significance_reason=reason,
                included=True,
                decision=decision,
            )
            return DreamPrepared(
                payload=prepared.model_dump(mode="json"),
                cost=inference.cost,
            )

    async def apply(self, claim: DreamClaim, payload: dict[str, Any]) -> int:
        async with get_db_session():
            prepared = SkillLearningPrepared.model_validate(payload)
            if runtime_settings.DREAM_SKILL_LEARNING_MODE != "learn":
                observed = prepared.model_copy(update={"application_mode": "observe"})
                await replace_prepared_payload(claim, observed.model_dump(mode="json"))
                return 0
            evidence = prepared.evidence
            if not prepared.included or evidence.owner_agent_id is None:
                learned = prepared.model_copy(update={"application_mode": "learn"})
                await replace_prepared_payload(claim, learned.model_dump(mode="json"))
                return 0
            result = await apply_learning_decision(
                agent_id=evidence.owner_agent_id,
                source_ref=f"galaris://task/{evidence.task_id}",
                source_fingerprint=evidence.fingerprint,
                allowed_evidence_refs={item.reference for item in evidence.observations},
                evidence_weight=_evidence_weight(prepared.significance_reason),
                decision=prepared.decision,
            )
            learned = prepared.model_copy(update={"application_mode": "learn"})
            await replace_prepared_payload(claim, learned.model_dump(mode="json"))

        if result.refresh_required:
            await refresh_learned_skill_runtime(evidence.owner_agent_id)
        return result.changed


skill_learning_mechanism = SkillLearningMechanism()


__all__ = ["SkillLearningMechanism", "skill_learning_mechanism"]
