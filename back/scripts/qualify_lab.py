"""Start budgeted Lab runs, compare model results, or verify a Process campaign."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import hashlib
import json
from math import ceil
import os
from pathlib import Path
from statistics import mean, median
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.lab.schemas import EvaluationRunDetail, EvaluationRunStart


class Policy(BaseModel):
    repetitions: int = Field(default=3, ge=3, le=20)
    max_drop_points: float = Field(default=5, ge=0, le=100)
    minimum_score: float = Field(default=80, ge=0, le=100)
    required_categories: list[str] = Field(default_factory=lambda: ["security", "robustness", "nominal"])
    zero_failure_categories: list[str] = Field(default_factory=lambda: ["security"])


class ProcessEvidence(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: UUID | None = None
    status: str | None = None
    exact_check: StrictBool | None = None
    definition_revision: int | None = Field(default=None, ge=1)
    duration_seconds: float | None = Field(default=None, ge=0, allow_inf_nan=False)


class ProcessCase(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: UUID
    position: int = Field(ge=0)
    status: str
    run_id: UUID | None
    evidence: ProcessEvidence


class ProcessCampaignPage(BaseModel):
    model_config = ConfigDict(hide_input_in_errors=True)
    id: UUID
    status: str
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    items: list[ProcessCase]


async def report_process_campaign(client: httpx.AsyncClient, identifier: UUID) -> dict[str, Any]:
    """Qualify only unique, complete runs with recorded exact output checks."""
    async def fetch(page: int) -> ProcessCampaignPage:
        response = await client.get(f"/api/evaluation/process-campaigns/{identifier}", params={"page": page})
        response.raise_for_status()
        return ProcessCampaignPage.model_validate(response.json())

    first = await fetch(1)
    cases: list[ProcessCase] = []
    pages = max(1, (first.total + first.page_size - 1) // first.page_size)
    for number in range(1, pages + 1):
        page = first if number == 1 else await fetch(number)
        if (page.id, page.status, page.total, page.page, page.page_size) != (
            identifier, first.status, first.total, number, first.page_size,
        ):
            raise ValueError("Process campaign changed during inspection")
        expected_items = min(first.page_size, first.total - (number - 1) * first.page_size)
        if len(page.items) != expected_items:
            raise ValueError("Process campaign page is incomplete")
        cases.extend(page.items)

    failures: list[str] = []
    if first.status != "completed" or not cases:
        failures.append("Campaign must contain completed cases")
    if ([case.position for case in cases] != list(range(first.total))
            or len({case.id for case in cases}) != first.total):
        failures.append("Case positions or identities are missing or duplicated")
    if (len({case.run_id for case in cases}) != first.total
            or any(case.run_id is None or case.evidence.id != case.run_id for case in cases)):
        failures.append("Each case must identify a distinct Process run with matching evidence")
    if any(case.status != "success" or case.evidence.status != "success" for case in cases):
        failures.append("Every Process run must succeed")
    if any(case.evidence.exact_check is not True for case in cases):
        failures.append("Every case must have a passing exact output check")
    revisions = {case.evidence.definition_revision for case in cases}
    if len(revisions) != 1 or None in revisions:
        failures.append("All cases must use a single recorded Process definition revision")

    durations = sorted(case.evidence.duration_seconds for case in cases if case.evidence.duration_seconds is not None)
    return {
        "campaign_id": str(identifier), "qualified": not failures, "failures": failures,
        "status": first.status, "case_count": first.total,
        "case_statuses": dict(Counter(case.status for case in cases)),
        "exact_matches": sum(case.evidence.exact_check is True for case in cases),
        "definition_revision": next(iter(revisions)) if len(revisions) == 1 else None,
        "duration_samples": len(durations),
        "median_seconds": round(median(durations), 3) if durations else None,
        "p95_seconds": round(durations[ceil(0.95 * len(durations)) - 1], 3) if durations else None,
    }


def compare(baseline: EvaluationRunDetail, candidate: EvaluationRunDetail, policy: Policy) -> dict[str, Any]:
    failures: list[str] = []
    if baseline.id == candidate.id:
        failures.append("Baseline and candidate must be independent runs")
    signatures: list[dict[tuple[str, int], str]] = []
    scores: list[dict[str, list[float]]] = []
    pass_rates: list[dict[str, list[float]]] = []
    for label, run in (("baseline", baseline), ("candidate", candidate)):
        if run.status != "completed" or run.completed_cases != run.total_cases or len(run.results) != run.total_cases:
            failures.append(f"{label}: incomplete run")
        if run.repetitions < policy.repetitions or not run.results:
            failures.append(f"{label}: insufficient repetitions")
        if run.max_cost is None or run.cost > run.max_cost or run.stop_reason:
            failures.append(f"{label}: missing or exceeded budget")
        if run.configuration_snapshot.get("dataset_purpose") not in {"validation", "holdout"}:
            failures.append(f"{label}: dataset must be validation or holdout")
        signature: dict[tuple[str, int], str] = {}
        grouped: dict[str, list[float]] = defaultdict(list)
        passed: dict[str, list[float]] = defaultdict(list)
        repetitions: dict[str, set[int]] = defaultdict(set)
        for result in run.results:
            snapshot = result.case_snapshot
            identifier = str(snapshot.get("id", ""))
            key = (identifier, result.repetition)
            if not identifier or key in signature:
                failures.append(f"{label}: missing or duplicate case identity")
            frozen = {name: snapshot.get(name) for name in ("id", "input_data", "expected_output", "categories")}
            signature[key] = hashlib.sha256(json.dumps(frozen, sort_keys=True).encode()).hexdigest()
            repetitions[identifier].add(result.repetition)
            categories = snapshot.get("categories", [])
            if not categories or result.error or result.score_percent is None or result.verdict not in {"pass", "fail"}:
                failures.append(f"{label}: unclassified, failed or inconclusive case {identifier}")
                continue
            checks = result.score_details.get("checks", [])
            checks_pass = all(check.get("passed") is True for check in checks)
            for category in categories:
                grouped[category].append(result.score_percent)
                passed[category].append(100.0 if result.verdict == "pass" and checks_pass else 0.0)
                if category in policy.zero_failure_categories and (result.verdict != "pass" or not checks_pass):
                    failures.append(f"{label}: critical case failed {identifier}")
        if any(value != set(range(1, run.repetitions + 1)) for value in repetitions.values()):
            failures.append(f"{label}: missing case repetitions")
        if not set(policy.required_categories).issubset(grouped):
            failures.append(f"{label}: required categories missing")
        signatures.append(signature)
        scores.append(grouped)
        pass_rates.append(passed)
    if signatures[0] != signatures[1]:
        failures.append("Corpus snapshots or repetitions differ")
    if baseline.score_version != candidate.score_version or baseline.judge_llm_snapshot != candidate.judge_llm_snapshot:
        failures.append("Judge or scoring version differs")
    categories: dict[str, dict[str, float]] = {}
    for category in scores[0].keys() & scores[1].keys():
        old, new = mean(scores[0][category]), mean(scores[1][category])
        old_pass, new_pass = mean(pass_rates[0][category]), mean(pass_rates[1][category])
        categories[category] = {"baseline": old, "candidate": new, "delta": new - old,
                                "baseline_pass_percent": old_pass, "candidate_pass_percent": new_pass,
                                "candidate_minimum": min(scores[1][category])}
        if new < policy.minimum_score or new < old - policy.max_drop_points or new_pass < old_pass - policy.max_drop_points:
            failures.append(f"Category regressed: {category}")
    return {"qualified": not failures, "failures": failures, "categories": categories,
            "baseline_run": str(baseline.id), "candidate_run": str(candidate.id),
            "candidate_cost": candidate.cost, "policy": policy.model_dump(),
            "scope": "Lab corpus comparison; model judgments do not prove external delivery"}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--mechanism", default="task_executor")
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--start-dataset")
    parser.add_argument("--process-campaign", type=UUID, help="Verify an existing Lab Process campaign without mutating it")
    parser.add_argument("--llm-id", type=int)
    parser.add_argument("--judge-llm-id", type=int)
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--policy", type=Path, default=Path(__file__).parents[1] / "lab-qualification.json")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    address = urlparse(str(args.base_url))
    if address.scheme != "https" and not (address.scheme == "http" and address.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS or loopback HTTP")
    if address.username or address.password:
        parser.error("Credentials belong in LAB_ACCESS_TOKEN, not in the URL")
    token = os.environ.get("LAB_ACCESS_TOKEN")
    if not token:
        parser.error("LAB_ACCESS_TOKEN is required")
    if args.process_campaign and (args.start_dataset or args.baseline or args.candidate
                                  or args.llm_id is not None or args.judge_llm_id is not None or args.max_cost is not None):
        parser.error("Process campaign verification is a separate operation")
    prefix = f"/api/evaluation/{args.mechanism}"
    async with httpx.AsyncClient(base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        if args.process_campaign:
            result = await report_process_campaign(client, args.process_campaign)
        elif args.start_dataset:
            if args.llm_id is None or args.max_cost is None or args.baseline or args.candidate:
                parser.error("Starting requires --llm-id and --max-cost; comparison is a separate operation")
            policy = Policy.model_validate_json(args.policy.read_text())
            payload = EvaluationRunStart(llm_id=args.llm_id, judge_llm_id=args.judge_llm_id,
                                         max_cost=args.max_cost, repetitions=policy.repetitions)
            response = await client.post(f"{prefix}/datasets/{args.start_dataset}/runs", json=payload.model_dump())
            response.raise_for_status()
            result = {"started_run": response.json()["id"], "qualified": False, "budget": args.max_cost}
        else:
            if not args.baseline or not args.candidate:
                parser.error("Comparison requires --baseline and --candidate")
            policy = Policy.model_validate_json(args.policy.read_text())
            runs: list[EvaluationRunDetail] = []
            for identifier in (args.baseline, args.candidate):
                response = await client.get(f"{prefix}/runs/{identifier}")
                response.raise_for_status()
                runs.append(EvaluationRunDetail.model_validate(response.json()))
            result = compare(runs[0], runs[1], policy)
        default_report = "process-campaign-qualification.json" if args.process_campaign else "lab-qualification.json"
        output = args.output or Path("/repo/artifacts") / default_report
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result))
        if not args.start_dataset and not result["qualified"]:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
