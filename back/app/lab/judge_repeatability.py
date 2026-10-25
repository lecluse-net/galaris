"""Read-only repeatability of a frozen judge on identical candidate outputs."""

import asyncio
import json
from collections import defaultdict
from hashlib import sha256
from math import fsum, isfinite
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, JsonValue
from sqlalchemy import String, and_, cast, func, select

from core.database import get_db
from .models import LabEvaluationDataset, LabEvaluationRun, LabEvaluationRunCase, LabJudgmentCampaign, LabJudgmentResult
from .schemas import EvaluationMechanism
from .statistics import CaseEstimate, estimate


class RepeatabilityGroup(BaseModel):
    configuration_digest: str
    configuration: dict[str, JsonValue]
    campaign_ids: list[UUID]
    outputs: int
    expected_judgments: int
    recorded_judgments: int
    usable_judgments: int
    missing_judgments: int
    unusable_judgments: int
    repeated_outputs: int
    judgment_pairs: int
    absolute_score_difference: CaseEstimate
    verdict_disagreement_percent: CaseEstimate


class JudgeRepeatabilityReport(BaseModel):
    run_id: UUID
    method: Literal["fixed-output-judge-repeatability/v1"] = "fixed-output-judge-repeatability/v1"
    groups: list[RepeatabilityGroup]
    unqualified_campaign_ids: list[UUID]


class CampaignEvidence(BaseModel):
    id: UUID
    configuration: dict[str, JsonValue]


class JudgmentEvidence(BaseModel):
    campaign_id: UUID
    result_id: UUID
    case_key: str
    candidate_status: str | None
    status: str
    error: str | None
    score_percent: float | None
    verdict: str
    rubric_version: str | None


def _rubric_version(configuration: dict[str, JsonValue]) -> str | None:
    model, rubric = configuration.get("model"), configuration.get("rubric")
    threshold = configuration.get("pass_threshold")
    if (not isinstance(model, dict) or not isinstance(model.get("binding"), str) or not model["binding"]
            or not isinstance(rubric, dict) or not rubric
            or isinstance(threshold, bool) or not isinstance(threshold, (int, float))
            or not isfinite(threshold) or not 0 <= threshold <= 100
            or "reasoning_effort" not in configuration):
        return None
    version, dimensions = rubric.get("version"), rubric.get("dimensions")
    return version if isinstance(version, str) and version and isinstance(dimensions, list) and dimensions else None


def summarize_repeatability(
    run_id: UUID, campaigns: list[CampaignEvidence], judgments: list[JudgmentEvidence], outputs: int,
) -> JudgeRepeatabilityReport:
    """Average campaign pairs within outputs, then outputs within source cases.

    Pair enumeration is avoided: scores use sorted absolute differences, and
    binary verdict disagreement uses pass_count * fail_count. Neither campaign
    pairs nor candidate repetitions become independent source observations.
    """
    configurations: dict[str, list[CampaignEvidence]] = defaultdict(list)
    unqualified: list[UUID] = []
    for campaign in campaigns:
        if _rubric_version(campaign.configuration) is None:
            unqualified.append(campaign.id)
        else:
            key = json.dumps(campaign.configuration, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            configurations[key].append(campaign)
    by_campaign: dict[UUID, list[JudgmentEvidence]] = defaultdict(list)
    for judgment in judgments:
        by_campaign[judgment.campaign_id].append(judgment)
    groups: list[RepeatabilityGroup] = []
    for key, members in configurations.items():
        version = _rubric_version(members[0].configuration)
        recorded = [row for campaign in members for row in by_campaign[campaign.id]]
        usable = [row for row in recorded if row.candidate_status == "completed"
                  and row.status == "completed" and not row.error
                  and row.score_percent is not None and isfinite(row.score_percent)
                  and 0 <= row.score_percent <= 100 and row.verdict in {"pass", "fail"}
                  and row.rubric_version == version]
        by_output: dict[UUID, list[JudgmentEvidence]] = defaultdict(list)
        for row in usable:
            by_output[row.result_id].append(row)
        score_clusters: dict[str, list[float]] = defaultdict(list)
        verdict_clusters: dict[str, list[float]] = defaultdict(list)
        repeated = pairs = 0
        for rows in by_output.values():
            if len(rows) < 2:
                continue
            repeated += 1
            pair_count = len(rows) * (len(rows) - 1) // 2
            pairs += pair_count
            scores = sorted(row.score_percent for row in rows if row.score_percent is not None)
            absolute_sum = fsum((2 * index - len(scores) + 1) * score for index, score in enumerate(scores))
            score_clusters[rows[0].case_key].append(max(0.0, min(100.0, absolute_sum / pair_count)))
            passes = sum(row.verdict == "pass" for row in rows)
            verdict_clusters[rows[0].case_key].append(100 * passes * (len(rows) - passes) / pair_count)
        groups.append(RepeatabilityGroup(
            configuration_digest=sha256(key.encode()).hexdigest(), configuration=members[0].configuration,
            campaign_ids=[campaign.id for campaign in members], outputs=outputs,
            expected_judgments=outputs * len(members), recorded_judgments=len(recorded),
            usable_judgments=len(usable), missing_judgments=outputs * len(members) - len(recorded),
            unusable_judgments=len(recorded) - len(usable), repeated_outputs=repeated, judgment_pairs=pairs,
            absolute_score_difference=estimate(list(score_clusters.values()), bounds=(0, 100)),
            verdict_disagreement_percent=estimate(list(verdict_clusters.values()), bounds=(0, 100)),
        ))
    return JudgeRepeatabilityReport(run_id=run_id, groups=groups, unqualified_campaign_ids=unqualified)


async def read_repeatability(mechanism: EvaluationMechanism, run_id: UUID) -> JudgeRepeatabilityReport:
    """Project historical measurements only; never reload candidate/judge bodies."""
    exists = await get_db().scalar(select(LabEvaluationRun.id).join(LabEvaluationDataset).where(
        LabEvaluationRun.id == run_id, LabEvaluationDataset.mechanism == mechanism,
    ))
    if exists is None:
        raise LookupError("Lab run not found.")
    campaigns = [CampaignEvidence.model_validate(dict(row)) for row in (await get_db().execute(
        select(LabJudgmentCampaign.id, LabJudgmentCampaign.configuration)
        .where(LabJudgmentCampaign.run_id == run_id)
        .order_by(LabJudgmentCampaign.sequence, LabJudgmentCampaign.id)
    )).mappings()]
    # A new campaign appearing after the previous read belongs to the next report.
    result = LabEvaluationRunCase
    judgment = LabJudgmentResult
    rows = (await get_db().execute(select(
        result.id.label("output_id"), judgment.campaign_id, judgment.result_id,
        cast(func.jsonb_build_array(result.case_snapshot["input_data"], result.case_snapshot["expected_output"]), String).label("case_key"),
        result.score_details["candidate_status"].astext.label("candidate_status"),
        judgment.status, judgment.error, judgment.score_percent, judgment.verdict,
        judgment.output["rubric_version"].astext.label("rubric_version"),
    ).select_from(result).outerjoin(judgment, and_(
        judgment.result_id == result.id,
        judgment.campaign_id.in_([campaign.id for campaign in campaigns]),
    )).where(result.run_id == run_id).order_by(result.id, judgment.campaign_id))).mappings().all()
    # Count outputs and their measurements in one statement snapshot, including
    # outputs without a judgment. Concurrent deletions cannot make missing < 0.
    evidence = [JudgmentEvidence.model_validate(dict(row)) for row in rows if row["campaign_id"] is not None]
    outputs = len({row["output_id"] for row in rows})
    return await asyncio.to_thread(summarize_repeatability, run_id, campaigns, evidence, outputs)
