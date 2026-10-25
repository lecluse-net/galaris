"""Exact scoring and paired case-cluster uncertainty, including failed runs."""

from __future__ import annotations

import json
import random
import hashlib
from collections import defaultdict
from pathlib import Path
from typing import Any, cast

from .corpus import save, source_hash


def answer_object(answer: str) -> dict[str, Any] | None:
    """Accept one unambiguous structured answer, including a surrounding explanation."""
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    index = 0
    while index < len(answer):
        if answer[index] != "{":
            index += 1
            continue
        try:
            value, length = decoder.raw_decode(answer[index:])
        except ValueError:
            index += 1
            continue
        if isinstance(value, dict):
            objects.append(cast(dict[str, Any], value))
        index += length
    return objects[0] if len(objects) == 1 else None


def score(answer: str, expected: dict[str, Any]) -> bool:
    # No whitespace/case coercion, unordered-list coercion or substring success.
    parsed = answer_object(answer)
    if parsed is None or not expected.keys() <= parsed.keys():
        return False

    def exact(a: Any, b: Any) -> bool:
        if type(a) is not type(b):
            return False
        if isinstance(a, dict):
            mapping = cast(dict[str, Any], a)
            return mapping.keys() == b.keys() and all(exact(mapping[k], b[k]) for k in mapping)
        if isinstance(a, list):
            items = cast(list[Any], a)
            return len(items) == len(b) and all(exact(x, y) for x, y in zip(items, b, strict=True))
        return a == b

    return exact({key: parsed[key] for key in expected}, expected)


def interval(values: list[float]) -> list[float]:
    values.sort()
    return [values[int((len(values) - 1) * p)] for p in (0.025, 0.975)]


def compare(rows: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    expected_keys = {(r["case"], r["repetition"], r["arm"]) for r in manifest["runs"]}
    keys = [(r["case"], r["repetition"], r["arm"]) for r in rows]
    if len(keys) != len(set(keys)) or set(keys) != expected_keys:
        raise ValueError("Missing, duplicate or unexpected paired results")
    groups: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[row["case"]].append(row)

    def aggregate(selected: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for arm in ("mcp", "filesystem"):
            runs = [r for r in selected if r["arm"] == arm]
            passed = sum(r["passed"] for r in runs)
            costs = [r.get("cost_usd") for r in runs]
            cost = (
                sum(float(c) for c in costs if isinstance(c, (float, int)))
                if all(isinstance(c, (float, int)) for c in costs)
                else None
            )
            result[arm] = dict(
                runs=len(runs),
                passed=passed,
                success_rate=passed / len(runs),
                cost_usd=cost,
                cost_per_success=cost / passed if cost is not None and passed else None,
                input_tokens=sum(r.get("input_tokens", 0) for r in runs),
                output_tokens=sum(r.get("output_tokens", 0) for r in runs),
                seconds=sum(r.get("seconds", 0) for r in runs),
                tool_calls=sum(r.get("tool_calls", 0) for r in runs),
            )
        return result

    def differences(arms: dict[str, Any]) -> tuple[float, float | None]:
        a, b = arms["mcp"], arms["filesystem"]
        gain = b["success_rate"] - a["success_rate"]
        reduction = (
            1 - b["cost_per_success"] / a["cost_per_success"]
            if a["cost_per_success"] and b["cost_per_success"] is not None
            else None
        )
        return gain, reduction

    arms = aggregate(rows)
    gain, reduction = differences(arms)
    rng = random.Random(manifest["decision"]["bootstrap_seed"])
    cases = sorted(groups)
    gains: list[float] = []
    reductions: list[float] = []
    for _ in range(manifest["decision"]["bootstrap_samples"]):
        sample = [r for _ in cases for r in groups[rng.choice(cases)]]
        dg, dr = differences(aggregate(sample))
        gains.append(dg)
        if dr is not None:
            reductions.append(dr)
    gain_ci = interval(gains)
    cost_ci = interval(reductions) if len(reductions) == len(gains) else None
    safety = any(
        r.get("identity_error") or r.get("silent_failure") or not r.get("access_verified")
        for r in rows
    )
    quality = all(r.get("usage_verified") and not r.get("infrastructure_error") for r in rows)
    thresholds = manifest["decision"]
    positive = (
        not safety
        and quality
        and (
            (gain >= thresholds["success_gain"] and gain_ci[0] > 0)
            or (
                reduction is not None
                and reduction >= thresholds["cost_reduction"]
                and cost_ci is not None
                and cost_ci[0] > 0
                and gain_ci[0] > -thresholds["noninferiority_margin"]
            )
        )
    )
    return dict(
        complete=True,
        phase=manifest["phase"],
        arms=arms,
        paired_case_count=len(cases),
        success_gain=gain,
        success_gain_ci95=gain_ci,
        cost_reduction=reduction,
        cost_reduction_ci95=cost_ci,
        safety_regression=safety,
        measurement_valid=quality,
        per_case={case: aggregate(groups[case]) for case in cases},
        decision="pilot_only"
        if manifest["phase"] == "pilot"
        else "invalid_measurement"
        if not quality
        else "continue_design"
        if positive
        else "stop_fuse",
        limits=[
            "Synthetic connected provider; native domain ACLs and real remote transport are not qualified.",
            "Local-directory latency is optimistic; no FUSE capacity claim.",
            "Case-cluster bootstrap; repetitions are not independent missions.",
            "Provider cache is observed, not reset; no second campaign after inspecting results.",
        ],
    )


def report(root: Path) -> dict[str, Any]:
    manifest = json.loads((root / "manifest.json").read_text())
    if (
        "experiment_source_sha256" in manifest
        and source_hash() != manifest["experiment_source_sha256"]
    ):
        raise ValueError(
            "Campaign sources changed during measurement; do not publish this comparison"
        )
    actual_files = {
        p.relative_to(root / "corpus").as_posix()
        for p in (root / "corpus").rglob("*")
        if p.is_file()
    }
    if actual_files != {r["path"] for r in manifest["files"]} or any(
        hashlib.sha256((root / "corpus" / r["path"]).read_bytes()).hexdigest() != r["sha256"]
        for r in manifest["files"]
    ):
        raise ValueError("Campaign corpus changed during measurement")
    cases = {c["id"]: c for c in manifest["cases"]}
    rows: list[dict[str, Any]] = []
    for run in manifest["runs"]:
        path = root / "results" / run["id"] / "result.json"
        metrics_path = root / "metrics" / (run["id"] + ".json")
        if not path.exists() or not metrics_path.exists():
            raise ValueError("Campaign incomplete; missing runtime result or provider evidence")
        result = json.loads(path.read_text())
        metrics = json.loads(metrics_path.read_text())
        answer = result.get("answer", "")
        correct = score(answer, cases[run["case"]]["expected"])
        tools = result.get("tools", [])
        file_calls = metrics.get("file_calls", [])
        access = (
            bool(file_calls)
            if run["arm"] == "mcp"
            else any(
                name in {"read_file", "search_files", "terminal", "list_directory"}
                for name in tools
            )
            and not file_calls
        )
        if run["arm"] == "mcp":
            # Both arms may use the shell; A has no corpus mount. Validate real
            # facade evidence instead of prohibiting calculation tools.
            family = cases[run["case"]]["family"]
            if family == "failure":
                access = access and any(c.get("error") for c in file_calls)
            elif family == "pagination":
                access = access and any(c["tool"] == "file_list" for c in file_calls)
            else:
                access = access and any(
                    c["tool"] == "file_read"
                    or (c["tool"] == "file_search" and c["arguments"].get("mode") == "text")
                    for c in file_calls
                )
        expected = cases[run["case"]]["expected"]
        mapping = answer_object(answer) or {}
        identity_error = any(
            mapping.get(k) != v for k, v in expected.items() if k.endswith("uri") and k in mapping
        )
        silent_failure = (
            cases[run["case"]]["family"] == "failure" and mapping.get("complete") is True
        )
        runtime_authority_missing = "BLOCKED: No Galaris" in json.dumps(result.get("messages", []))
        measurement_verified = (
            metrics.get("usage_verified", False)
            and metrics.get("model_calls", 0) > 0
            and len(metrics.get("usage", [])) == metrics.get("model_calls")
        )
        row = {
            **run,
            **metrics,
            "correct_answer": correct,
            "access_verified": access,
            "identity_error": identity_error,
            "silent_failure": silent_failure,
            "usage_verified": measurement_verified,
            "infrastructure_error": result.get("error")
            or ("Missing runtime authority" if runtime_authority_missing else None),
            "seconds": result.get("seconds", 0),
            "tool_calls": len(tools),
            "passed": correct and access and not result.get("error"),
        }
        rows.append(row)
    result = compare(rows, manifest)
    save(root / "scores.json", rows)
    save(root / "summary.json", result)
    return result
