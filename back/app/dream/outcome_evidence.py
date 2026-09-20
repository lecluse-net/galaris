"""Deterministic, bounded and redacted Task outcome evidence."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from uuid import UUID

from app.goal import get_goal_outcome_for_task
from app.memory import list_task_memory_usages, redact_secrets
from app.task import TaskOutcomeObservation, get_task_outcome_observation

from .contracts import (
    SignificanceReason,
    TaskOutcomeEvidence,
    TaskOutcomeEvidenceItem,
)
from .language import source_language


_MAX_ATTEMPTS = 10
_MAX_TOOLS = 20
_MAX_CHILDREN = 12
_TRANSIENT_RE = re.compile(
    r"\b(timeout|timed out|rate.?limit|provider|network|connection|dns|temporar|503|502)\b",
    re.IGNORECASE,
)
_INTERRUPTION_RE = re.compile(
    r"\b(cancel|cancelled|canceled|interrupt|preempt|barge.?in|arr[êe]t)\b",
    re.IGNORECASE,
)
_CORRECTION_RE = re.compile(
    r"\b(corrig|incorrect|faux|erreur|plut[oô]t|en fait|actually|instead|wrong|not what|should have)\b",
    re.IGNORECASE,
)
_VALIDATION_RE = re.compile(
    r"\b(parfait|merci|valid[ée]|confirm[ée]|correct|r[ée]ussi|fonctionne|worked|great|perfect|approved)\b",
    re.IGNORECASE,
)


def _safe(value: object, limit: int) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return ""
    redacted = redact_secrets(normalized)
    return (redacted or "[sensitive content omitted]")[:limit]


def _error_class(value: str) -> str:
    normalized = _safe(value, 2_000)
    if not normalized:
        return ""
    first_line = normalized.splitlines()[0]
    head = first_line.split(":", 1)[0].strip()
    return head[:120] if head else "error"


async def build_task_outcome_evidence(task_id: UUID) -> TaskOutcomeEvidence | None:
    observation = await get_task_outcome_observation(task_id)
    if observation is None:
        return None
    items = _task_observations(observation)
    goal = await get_goal_outcome_for_task(task_id)
    if goal is not None:
        goal_detail = "; ".join(
            value
            for value in (
                _safe(goal.reason, 600),
                _safe(goal.progress_summary, 600),
                *(_safe(value, 300) for value in goal.evidence[:5]),
            )
            if value
        )
        items.append(
            TaskOutcomeEvidenceItem(
                reference=f"goal-cycle:{goal.cycle_id}",
                kind="goal_judgement",
                status=goal.verdict,
                name="progress_changed" if goal.progress_changed else "no_progress",
                detail=goal_detail[:2_000],
            )
        )
    memory_ids: list[UUID] = []
    if observation.owner_agent_id is not None:
        usages = await list_task_memory_usages(
            task_id,
            agent_id=observation.owner_agent_id,
        )
        injected_usages = tuple(
            usage
            for usage in usages
            if usage.access_kind
            in {"context", "experience_planning", "experience_execution"}
        )
        memory_ids = list(
            dict.fromkeys(usage.memory_id for usage in injected_usages)
        )[:50]
        items.extend(
            TaskOutcomeEvidenceItem(
                reference=f"memory:{usage.memory_id}",
                kind="injected_memory",
                status=usage.access_kind,
                name=usage.memory_role,
            )
            for usage in injected_usages[:20]
        )
    material = {
        "task_id": str(observation.task_id),
        "owner_agent_id": observation.owner_agent_id,
        "language": source_language(observation.task_data.get("language")),
        "label": _safe(observation.label, 500),
        "objective": _safe(observation.objective, 4_000),
        "terminal_status": observation.status,
        "final_result": _safe(observation.result, 4_000),
        "normalized_error": _safe(observation.error, 2_000),
        "driver_code": _safe(observation.driver_code, 100),
        "model_code": _safe(observation.model_code, 100),
        "effort": _safe(observation.effort, 40),
        "route": _safe(observation.route, 40),
        "observations": [item.model_dump(mode="json") for item in items[:48]],
        "injected_memory_ids": [str(value) for value in memory_ids],
    }
    serialized = json.dumps(material, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    fingerprint = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return TaskOutcomeEvidence.model_validate({**material, "fingerprint": fingerprint})


def _task_observations(observation: TaskOutcomeObservation) -> list[TaskOutcomeEvidenceItem]:
    items: list[TaskOutcomeEvidenceItem] = [
        TaskOutcomeEvidenceItem(
            reference=f"galaris://task/{observation.task_id}",
            kind="terminal_result",
            status=observation.status,
            name=_error_class(observation.error),
            detail=_safe(observation.result or observation.error, 2_000),
        )
    ]
    for attempt in observation.attempts[:_MAX_ATTEMPTS]:
        items.append(
            TaskOutcomeEvidenceItem(
                reference=attempt.reference,
                kind="attempt",
                status=attempt.status,
                name=f"{attempt.phase}:{_error_class(attempt.error)}".rstrip(":"),
                detail=_safe(attempt.error, 1_000),
                retryable=attempt.retryable,
                duration_seconds=attempt.duration_seconds,
            )
        )
    for tool in observation.tools[:_MAX_TOOLS]:
        items.append(
            TaskOutcomeEvidenceItem(
                reference=tool.reference,
                kind="tool_result",
                status="success" if tool.success else "error",
                name=_safe(tool.name, 200),
                detail=_safe(tool.result, 1_200),
                duration_seconds=tool.duration_seconds,
            )
        )
    for child in observation.children[:_MAX_CHILDREN]:
        detail = _safe(child.result or child.error, 1_200)
        items.append(
            TaskOutcomeEvidenceItem(
                reference=child.reference,
                kind="child_result",
                status=child.status,
                name=_safe(child.label, 200),
                detail=detail,
            )
        )
    followup = observation.followup
    if followup is not None and not followup.sender_is_ai and followup.objective.strip():
        items.append(
            TaskOutcomeEvidenceItem(
                reference=f"galaris://task/{followup.task_id}",
                kind="human_followup",
                status="observed",
                detail=_safe(followup.objective, 1_500),
            )
        )
    if observation.task_data.get("action_guard_retried") is True:
        items.append(
            TaskOutcomeEvidenceItem(
                reference=f"galaris://task/{observation.task_id}",
                kind="guard_retry",
                status="triggered",
                detail="The action guard rejected an unverified action claim before retry.",
            )
        )
    return items


def significance_reason(evidence: TaskOutcomeEvidence) -> tuple[bool, SignificanceReason]:
    if evidence.owner_agent_id is None:
        return False, "unowned_task"
    human = [item.detail for item in evidence.observations if item.kind == "human_followup"]
    if any(_CORRECTION_RE.search(value) for value in human):
        return True, "explicit_human_correction"
    if any(_VALIDATION_RE.search(value) for value in human):
        return True, "explicit_human_validation"
    attempts = [item for item in evidence.observations if item.kind == "attempt"]
    statuses = [item.status.upper() for item in attempts]
    if any(status in {"ERROR", "RETRY"} for status in statuses) and any(
        status == "SUCCESS" for status in statuses
    ):
        return True, "recovered_after_failure"
    if any(item.kind == "guard_retry" for item in evidence.observations):
        return True, "guard_retry"
    failure_classes = Counter(
        item.name for item in attempts if item.status.upper() in {"ERROR", "RETRY"} and item.name
    )
    if any(count >= 2 for count in failure_classes.values()):
        return True, "repeated_failure"
    goal = next((item for item in evidence.observations if item.kind == "goal_judgement"), None)
    if goal is not None and goal.name == "progress_changed":
        return True, "goal_validation"
    if goal is not None and goal.status == "STOP" and goal.name == "no_progress":
        return True, "goal_refutation"
    child_statuses = {
        item.status for item in evidence.observations if item.kind == "child_result"
    }
    if "SUCCESS" in child_statuses and "ERROR" in child_statuses:
        return True, "mixed_plan"
    verified_tools = [
        item
        for item in evidence.observations
        if item.kind == "tool_result" and item.status == "success" and item.detail
    ]
    if evidence.terminal_status == "SUCCESS" and verified_tools:
        return True, "verified_tool_success"
    error_text = evidence.normalized_error
    if evidence.terminal_status == "ERROR":
        if _INTERRUPTION_RE.search(error_text):
            return False, "expected_interruption"
        if _TRANSIENT_RE.search(error_text) and len(attempts) <= 1:
            return False, "isolated_transient_failure"
        if error_text:
            return True, "definitive_failure"
    if evidence.terminal_status == "SUCCESS":
        return False, "unverified_success"
    return False, "no_reusable_signal"


__all__ = ["build_task_outcome_evidence", "significance_reason"]
