"""Start explicitly budgeted Lab runs or compare completed runs through the public API."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
from statistics import mean
from typing import Any
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from app.lab.schemas import EvaluationRunDetail, EvaluationRunStart


class Policy(BaseModel):
    repetitions: int = Field(default=3, ge=3, le=20)
    max_drop_points: float = Field(default=5, ge=0, le=100)
    minimum_score: float = Field(default=80, ge=0, le=100)
    required_categories: list[str] = Field(default_factory=lambda: ["security", "robustness", "nominal"])
    zero_failure_categories: list[str] = Field(default_factory=lambda: ["security"])


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
    parser.add_argument("--mechanism", default="briefing")
    parser.add_argument("--baseline")
    parser.add_argument("--candidate")
    parser.add_argument("--start-dataset")
    parser.add_argument("--llm-id", type=int)
    parser.add_argument("--judge-llm-id", type=int)
    parser.add_argument("--max-cost", type=float)
    parser.add_argument("--policy", type=Path, default=Path(__file__).parents[1] / "lab-qualification.json")
    parser.add_argument("--output", type=Path, default=Path("/repo/artifacts/lab-qualification.json"))
    args = parser.parse_args()
    address = urlparse(str(args.base_url))
    if address.scheme != "https" and not (address.scheme == "http" and address.hostname in {"localhost", "127.0.0.1", "::1"}):
        parser.error("Use HTTPS or loopback HTTP")
    if address.username or address.password:
        parser.error("Credentials belong in LAB_ACCESS_TOKEN, not in the URL")
    token = os.environ.get("LAB_ACCESS_TOKEN")
    if not token:
        parser.error("LAB_ACCESS_TOKEN is required")
    policy = Policy.model_validate_json(args.policy.read_text())
    prefix = f"/api/evaluation/{args.mechanism}"
    async with httpx.AsyncClient(base_url=args.base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30) as client:
        if args.start_dataset:
            if args.llm_id is None or args.max_cost is None or args.baseline or args.candidate:
                parser.error("Starting requires --llm-id and --max-cost; comparison is a separate operation")
            payload = EvaluationRunStart(llm_id=args.llm_id, judge_llm_id=args.judge_llm_id,
                                         max_cost=args.max_cost, repetitions=policy.repetitions)
            response = await client.post(f"{prefix}/datasets/{args.start_dataset}/runs", json=payload.model_dump())
            response.raise_for_status()
            result = {"started_run": response.json()["id"], "qualified": False, "budget": args.max_cost}
        else:
            if not args.baseline or not args.candidate:
                parser.error("Comparison requires --baseline and --candidate")
            runs: list[EvaluationRunDetail] = []
            for identifier in (args.baseline, args.candidate):
                response = await client.get(f"{prefix}/runs/{identifier}")
                response.raise_for_status()
                runs.append(EvaluationRunDetail.model_validate(response.json()))
            result = compare(runs[0], runs[1], policy)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        if not args.start_dataset and not result["qualified"]:
            raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
