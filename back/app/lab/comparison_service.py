"""Read-only comparison of frozen Lab evidence, shared by HTTP and MCP."""

from copy import deepcopy
from typing import Any, Literal, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.sql.selectable import CTE

from core.database import get_db
from .models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign
from .schemas import EvaluationMechanism, EvaluationRunRead, EvaluationRunCaseRead


async def _run(mechanism: EvaluationMechanism, identifier: UUID) -> LabEvaluationRun:
    row = await get_db().scalar(
        select(LabEvaluationRun)
        .join(LabEvaluationDataset)
        .where(LabEvaluationRun.id == identifier, LabEvaluationDataset.mechanism == mechanism)
    )
    if row is None:
        raise LookupError("Lab run not found.")
    return row


def _ambiguous_pairings(left_id: UUID, right_id: UUID) -> CTE:
    """Find shared evidence keys that cannot be paired one-to-one, in either direction."""
    input_data = LabEvaluationRunCase.case_snapshot["input_data"]
    expected_output = LabEvaluationRunCase.case_snapshot["expected_output"]
    counts = (
        select(
            LabEvaluationRunCase.run_id,
            LabEvaluationRunCase.repetition,
            input_data.label("input_data"),
            expected_output.label("expected_output"),
            func.count().label("result_count"),
        )
        .where(LabEvaluationRunCase.run_id.in_((left_id, right_id)))
        .group_by(
            LabEvaluationRunCase.run_id,
            LabEvaluationRunCase.repetition,
            input_data,
            expected_output,
        )
        .cte("pairing_counts")
    )
    left, right = counts.alias("left_counts"), counts.alias("right_counts")
    return (
        select(left.c.repetition, left.c.input_data, left.c.expected_output)
        .join(right, and_(
            left.c.repetition == right.c.repetition,
            left.c.input_data == right.c.input_data,
            left.c.expected_output == right.c.expected_output,
        ))
        .where(
            left.c.run_id == left_id,
            right.c.run_id == right_id,
            or_(left.c.result_count > 1, right.c.result_count > 1),
        )
        .cte("ambiguous_pairings")
    )


async def compare(
    mechanism: EvaluationMechanism,
    left_id: UUID,
    right_id: UUID,
    axis: Literal["model", "prompt", "parameters"],
    *,
    offset: int = 0,
    limit: int = 50,
    include_outputs: bool = False,
) -> dict[str, Any]:
    left, right = await _run(mechanism, left_id), await _run(mechanism, right_id)
    differences: list[str] = []
    left_fp, right_fp = (
        left.configuration_snapshot.get("fingerprints", {}),
        right.configuration_snapshot.get("fingerprints", {}),
    )
    for key in ("corpus", "candidate"):
        if not left_fp.get(key) or left_fp.get(key) != right_fp.get(key):
            differences.append(key)
    # A rejudgment changes the effective campaign, not the original run fingerprint.
    judges: list[dict[str, Any] | None] = []
    for item in (left, right):
        latest = await get_db().scalar(
            select(LabJudgmentCampaign)
            .where(LabJudgmentCampaign.run_id == item.id)
            .order_by(LabJudgmentCampaign.sequence.desc())
            .limit(1)
        )
        judges.append(latest.configuration if latest else None)
    if judges[0] is None or judges[0] != judges[1]:
        differences.append("judge")
    configurations = [deepcopy(item.configuration_snapshot) for item in (left, right)]
    # Experiment names, capture times and derived prompt hashes are not treatment changes.
    for configuration in configurations:
        for key in (
            "dataset_id",
            "dataset_revision",
            "dataset_name",
            "fingerprints",
            "resolved_at",
            "prompt_dataset_id",
            "prompt_dataset_name",
            "prompt_dataset_revision",
            "prompt_source",
            "prompt_suffix_sha256",
            "conversation_action_policy_sha256",
        ):
            configuration.pop(key, None)
    if configurations[0] != configurations[1]:
        differences.append("context")
    if axis == "parameters":
        for configuration in configurations:
            configuration.pop("parameters", None)
    if axis == "prompt":
        for configuration in configurations:
            configuration.pop("prompt_suffix", None)
            configuration.pop("system_prompt", None)
            for key in (
                "planner_configuration",
                "topic_configuration",
                "memory_extraction_configuration",
            ):
                nested = configuration.get(key)
                if isinstance(nested, dict):
                    cast(dict[str, Any], nested).pop("system_prompt", None)
    if axis != "model" and configurations[0] != configurations[1]:
        differences.append("other_configuration")
    allowed = {"candidate"} if axis == "model" else {"context"}
    blockers = [key for key in differences if key not in allowed]
    ambiguous = _ambiguous_pairings(left_id, right_id)
    if await get_db().scalar(select(select(ambiguous).exists())):
        blockers.append("ambiguous_case_pairing")
    ambiguous_item = select(ambiguous).where(
        ambiguous.c.repetition == LabEvaluationRunCase.repetition,
        ambiguous.c.input_data == LabEvaluationRunCase.case_snapshot["input_data"],
        ambiguous.c.expected_output == LabEvaluationRunCase.case_snapshot["expected_output"],
    ).exists()
    rows = (
        await get_db().execute(
            select(LabEvaluationRunCase, ambiguous_item)
            .where(LabEvaluationRunCase.run_id == left_id)
            .order_by(LabEvaluationRunCase.created_at, LabEvaluationRunCase.id)
            .offset(offset).limit(limit + 1)
        )
    ).tuples().all()
    compared: list[dict[str, Any]] = []
    for row, is_ambiguous in rows[:limit]:
        item = EvaluationRunCaseRead.model_validate(row).model_dump(mode="json")
        snapshot = item["case_snapshot"]
        matches = (
            await get_db().scalars(
                select(LabEvaluationRunCase)
                .where(
                    LabEvaluationRunCase.run_id == right_id,
                    LabEvaluationRunCase.repetition == item["repetition"],
                    LabEvaluationRunCase.case_snapshot["input_data"] == snapshot["input_data"],
                    LabEvaluationRunCase.case_snapshot["expected_output"]
                    == snapshot["expected_output"],
                )
                .order_by(LabEvaluationRunCase.id)
                .limit(2)
            )
        ).all()
        target = matches[0] if len(matches) == 1 and not is_ambiguous else None
        compared.append(
            {
                "left_result_id": item["id"],
                "right_result_id": str(target.id) if target else None,
                "pairing": "ambiguous" if is_ambiguous else "matched" if target else "missing",
                "name": snapshot.get("name"),
                "repetition": item["repetition"],
                "score_delta": target.score_percent - item["score_percent"]
                if target and target.score_percent is not None and item["score_percent"] is not None
                else None,
                "cost_delta": target.cost - item["cost"] if target else None,
                "duration_delta": target.duration - item["duration"] if target else None,
                "left_score": item["score_percent"],
                "right_score": target.score_percent if target else None,
                "left_verdict": item["verdict"],
                "right_verdict": target.verdict if target else None,
                "left_checks": item["score_details"],
                "right_checks": target.score_details if target else None,
                "left_judgment": item["judge_output"],
                "right_judgment": target.judge_output if target else None,
                "left_cost": item["cost"],
                "right_cost": target.cost if target else None,
                "left_duration": item["duration"],
                "right_duration": target.duration if target else None,
            }
        )
        if include_outputs:
            compared[-1].update({
                "input": snapshot["input_data"],
                "reference": snapshot["expected_output"],
                "left_output": item["actual_output"],
                "right_output": target.actual_output if target else None,
                "left_error": item["error"],
                "right_error": target.error if target else None,
            })
    return {
        "axis": axis,
        "comparable": not blockers,
        "differences": differences,
        "blockers": blockers,
        "left": EvaluationRunRead.model_validate(left).model_dump(mode="json"),
        "right": EvaluationRunRead.model_validate(right).model_dump(mode="json"),
        "items": compared,
        "next_offset": offset + limit if len(rows) > limit else None,
        "note": "Descriptive observed results; missing judgments are not successes. Repeat with reversed runs to inspect unmatched cases.",
    }
