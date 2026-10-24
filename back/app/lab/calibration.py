"""Calibrate against the authenticated reviewer's frozen human assessments only."""

import json
from collections import defaultdict

from .schemas import HumanCalibration, HumanReviewItem
from .statistics import CaseEstimate, estimate


def calibrate(items: list[HumanReviewItem]) -> HumanCalibration:
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    reviewed = paired = failures = false_passes = false_failures = disagreements = 0
    for item in items:
        if item.assessment is None:
            continue
        reviewed += 1
        judge = item.judge
        if (judge is None or judge.status != "completed" or judge.error
                or judge.score_percent is None or judge.verdict not in {"pass", "fail"}
                or item.human_score is None):
            continue
        paired += 1
        key = json.dumps([item.input, item.reference], sort_keys=True, ensure_ascii=False)
        groups["bias"][key].append(judge.score_percent - item.human_score)
        groups["absolute_error"][key].append(abs(judge.score_percent - item.human_score))
        disagreements += item.human_verdict != judge.verdict
        false_failures += item.human_verdict == "pass" and judge.verdict == "fail"
        if item.human_verdict == "fail":
            failures += 1
            false_passes += judge.verdict == "pass"
            groups["false_pass_rate"][key].append(100.0 if judge.verdict == "pass" else 0.0)
        if judge.output:
            scores = {dim["code"]: dim["score_percent"] for dim in item.assessment.get("dimensions", [])}
            for dim in judge.output.get("dimensions", []):
                if dim["code"] in scores:
                    groups["dimension:" + dim["code"]][key].append(dim["score_percent"] - scores[dim["code"]])
    def metric(name: str) -> CaseEstimate:
        return estimate(list(groups[name].values()))
    return HumanCalibration(eligible=len(items), reviewed=reviewed, paired=paired, missing_judgments=reviewed-paired,
        human_failures=failures, false_passes=false_passes, false_failures=false_failures,
        disagreements=disagreements, bias=metric("bias"), absolute_error=metric("absolute_error"),
        false_pass_rate=estimate(list(groups["false_pass_rate"].values()), bounds=(0, 100)), dimension_bias={
            name.removeprefix("dimension:"): metric(name) for name in list(groups) if name.startswith("dimension:")})
