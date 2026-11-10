"""Bounded paired prompt benchmark using real models and effect-free Lab tools.

Run only in development. Each arm uses the same production prompt builder, frozen
inputs, schemas, fixtures, model and reasoning effort. No business tool executes.
Results are synthetic tool-behaviour evidence, not end-to-end business validation.
"""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import re
from statistics import mean, median
import time
import traceback
from typing import Any, cast

from loguru import logger

from app.agent import ExecutorKind


CORPORA = (
    "outcome_capabilities_corpus_fr.json", "outcome_capabilities_corpus_en.json",
    "outcome_decisions_corpus_fr.json", "outcome_decisions_corpus_en.json",
    "outcome_transfer_corpus_fr.json", "outcome_transfer_corpus_en.json",
    "operating_knowledge_corpus_fr.json", "operating_knowledge_corpus_en.json",
    "latency_corpus_fr.json", "latency_corpus_en.json",
)
ROOT = Path(__file__).resolve().parents[1]


def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_cases() -> list[dict[str, Any]]:
    from app.lab.contracts import resolve_input
    cases: list[dict[str, Any]] = []
    for filename in CORPORA:
        corpus = json.loads((ROOT / "app/lab" / filename).read_text())
        for index, case in enumerate(corpus["cases"]):
            _, native = resolve_input(corpus["mechanism"], case["input_data"], corpus["parameters"])
            expected = case["expected_output"]
            if filename.startswith("latency_"):
                # Strengthen the qualitative latency reference with effect/fact oracles.
                oracles: list[dict[str, Any]] = [
                    {"max_tool_calls": 0, "response_values": ["56"]},
                    {"required_calls": [{"tool": "memory_search"}], "response_values": ["17"], "max_tool_calls": 2},
                    {"required_calls": [{"tool": "conversation_task_status", "arguments": {
                        "task_id": "galaris://task/00000000-0000-0000-0000-000000000041"}}],
                     "forbidden_tools": ["conversation_task_submit"], "max_tool_calls": 1},
                    {"required_calls": [{"tool": "conversation_task_submit", "argument_values": {
                        "objective": ["Orbe", "Nacre", "Sillage"]}}], "max_tool_calls": 1},
                ]
                # Foreground references have no transcript; only actual outputs are scored.
                expected = {**expected, "outcome_checks": oracles[index]}
            mechanisms = [corpus["mechanism"]]
            if filename.startswith("latency_"):
                mechanisms.append("voice_executor")
            for mechanism in mechanisms:
                cases.append({"key": f"{filename}/{index + 1}/{mechanism}", "name": case["name"],
                              "categories": case["categories"], "mechanism": mechanism,
                              "native": native, "expected": expected})
    return cases


def case_checks(case: dict[str, Any], actual: dict[str, Any]) -> list[dict[str, Any]]:
    from app.lab.objective_checks import check_output
    checked = actual
    facts = case["expected"].get("outcome_checks", {}).get("response_values", [])
    if any(re.fullmatch(r"\d{1,2}:\d{2}", value) for value in facts):
        # Equivalent clock notation must not turn a correct retrieved fact into a failure.
        response = re.sub(r"(?<!\d)([01]?\d|2[0-3])\s*h(?:\s*([0-5]\d))?(?!\w)",
            lambda match: f"{match[1]}:{match[2] or '00'}", str(actual.get("response", "")))
        checked = {**actual, "response": response}
    checks = check_output(case["mechanism"], case["native"], checked, expected=case["expected"])
    # Older latency cases have an action reference, without an outcome oracle.
    if "outcome_checks" not in case["expected"] and "action" in case["expected"]:
        checks.append({"code": "expected_action", "passed": actual.get("action") == case["expected"]["action"],
                       "critical": True, "detail": "The requested direct answer, status read or launch occurred"})
    return checks


def rescore(output: Path) -> dict[str, Any]:
    """Recheck saved outputs only; retain the original scores and frozen evidence."""
    manifest = json.loads((output / "manifest.json").read_text())
    cases = json.loads((output / "cases.json").read_text())
    if digest(cases) != manifest["cases_sha256"]:
        raise ValueError("Frozen cases changed; refuse rescoring")
    mapping = {case["key"]: case for case in cases}
    results = [json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
    corrected: list[dict[str, Any]] = []
    for row in results:
        if "output" in row:
            checks = case_checks(mapping[row["case"]], row["output"])
            row = {**row, "original_passed": row["passed"], "original_checks": row["checks"],
                   "checks": checks, "passed": all(check["passed"] for check in checks)}
        corrected.append(row)
    report = aggregate(corrected, planned=manifest["planned"])
    report["rescoring"] = {
        "reason": "Accept equivalent clock notation and compare receipt arguments with declared defaults bound; required effects and budgets are unchanged.",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "original_results_sha256": hashlib.sha256((output / "results.jsonl").read_bytes()).hexdigest(),
        "observed_correction": True,
        "changed_observations": sum(row.get("original_passed", row["passed"]) != row["passed"] for row in corrected),
    }
    (output / "rescored-results.json").write_text(json.dumps(corrected, ensure_ascii=False, indent=2))
    (output / "rescored-summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


def aggregate(results: list[dict[str, Any]], *, planned: int) -> dict[str, Any]:
    """Pair repetitions, then bootstrap independent scenario clusters, not episodes."""
    variants: dict[str, Any] = {}
    for variant in ("before", "after"):
        rows = [row for row in results if row["variant"] == variant]
        measured_calls = [row["tool_calls_count"] for row in rows if "tool_calls_count" in row]
        categories: dict[str, list[bool]] = defaultdict(list)
        mechanisms: dict[str, list[bool]] = defaultdict(list)
        corpora: dict[str, list[bool]] = defaultdict(list)
        for row in rows:
            for category in row["categories"]:
                categories[category].append(row["passed"])
            mechanisms[str(row.get("mechanism", "unknown"))].append(row["passed"])
            corpora[str(row["case"]).split("/")[0]].append(row["passed"])
        variants[variant] = {
            "observations": len(rows), "passed": sum(row["passed"] for row in rows),
            "pass_rate": mean(row["passed"] for row in rows) if rows else None,
            "median_seconds": median(row["seconds"] for row in rows) if rows else None,
            "mean_tool_calls": mean(measured_calls) if measured_calls else None,
            "tool_call_measurements": len(measured_calls),
            "missing_tool_call_measurements": len(rows) - len(measured_calls),
            "recorded_cost_usd": sum(row["cost"]["recorded_cost"] for row in rows),
            "unknown_cost_calls": sum(row["cost"]["unknown_calls"] for row in rows),
            "infrastructure_observations": sum(infrastructure_failure(row) for row in rows),
            "failed_checks": dict(Counter(check["code"] for row in rows for check in row.get("checks", []) if not check["passed"])),
            "errors": dict(Counter(row["error_type"] for row in rows if row.get("error_type"))),
            "categories": {key: {"observations": len(values), "pass_rate": mean(values)}
                           for key, values in sorted(categories.items())},
            "mechanisms": {key: {"observations": len(values), "pass_rate": mean(values)}
                           for key, values in sorted(mechanisms.items())},
            "corpora": {key: {"observations": len(values), "pass_rate": mean(values)}
                        for key, values in sorted(corpora.items())},
        }
    pairs: dict[tuple[str, int], dict[str, dict[str, Any]]] = defaultdict(dict)
    for row in results:
        pairs[row["case"], row["repetition"]][row["variant"]] = row
    differences: dict[str, list[float]] = defaultdict(list)
    wins = losses = ties = excluded_pairs = 0
    paired_cases: set[str] = set()
    for (key, _), arms in pairs.items():
        if set(arms) != {"before", "after"}:
            continue
        if any(infrastructure_failure(arm) for arm in arms.values()):
            excluded_pairs += 1
            continue
        delta = float(arms["after"]["passed"]) - float(arms["before"]["passed"])
        # Translations and foreground modes of one scenario are correlated evidence.
        group = re.sub(r"-(?:fr|en)$", "", str(arms["before"].get("name") or key))
        differences[group].append(delta)
        paired_cases.add(key)
        wins += delta > 0
        losses += delta < 0
        ties += delta == 0
    clusters = [mean(values) for values in differences.values()]
    interval = None
    if clusters:
        rng = random.Random(20261110)
        samples = sorted(mean(rng.choices(clusters, k=len(clusters))) for _ in range(5000))
        interval = [samples[125], samples[4874]]
    return {"planned": planned, "completed": len(results), "complete": len(results) == planned,
            "variants": variants, "paired": {"cases": len(paired_cases), "scenario_clusters": len(clusters),
                "excluded_infrastructure_pairs": excluded_pairs, "wins": wins, "losses": losses,
                "ties": ties, "mean_case_delta": mean(clusters) if clusters else None,
                "case_cluster_bootstrap_95_interval": interval},
            "limitations": ["Synthetic fixtures simulate effects; no business operation executes.",
                "Checks establish required calls, arguments and selected facts, not complete prose quality.",
                "Public validation cases are not a private production holdout.",
                "Repetitions, translations and foreground variants are clustered by scenario.",
                "Pairs with infrastructure failures are excluded from the causal difference estimate."]}


@dataclass
class Limits:
    max_cost: float
    max_episodes: int
    concurrency: int
    timeout_seconds: float


def model_failure(error: Exception) -> bool:
    """A duplicate simulated call is failed model behaviour, not a provider outage."""
    return (type(error).__name__ in {"UnexpectedModelBehavior", "UsageLimitExceeded"}
            or (type(error) is ValueError and str(error) == "The tool response fixture is exhausted"))


def infrastructure_failure(row: dict[str, Any]) -> bool:
    return bool(row.get("error_type") and row.get("error_kind") != "model_behavior"
                and row["error_type"] not in {"UnexpectedModelBehavior", "UsageLimitExceeded"})


async def benchmark(output: Path, *, repetitions: int, limits: Limits, execute: bool,
                    pilot: int | None = None, resume: bool = False,
                    selected_cases: list[str] | None = None) -> dict[str, Any]:
    from core.settings import settings
    if not settings.is_dev:
        raise ValueError("Operating-knowledge benchmarks require APP_ENV=dev")
    if output.exists() and not resume:
        raise ValueError("Preserve existing evidence; choose a new output directory")
    from core.database import get_db_session, load_models
    from core.params import Params, params_service
    from modules import load_llm_provider_modules
    from app.llm import llm_service, model_usages, reasoning_effort_scope
    from app.llm.facade import llm_call_accounting
    from app.lab.mechanism_registry import build_executor_benchmark_prompt, evaluate_mechanism, get_mechanism
    from app.lab.inference_profile import model_binding

    load_models()
    load_llm_provider_modules()
    cases = load_cases()
    prior = json.loads((output / "manifest.json").read_text()) if resume else None
    if prior is not None:
        cases = json.loads((output / "cases.json").read_text())
        if digest(cases) != prior["cases_sha256"] or repetitions != prior["repetitions"]:
            raise ValueError("Resume requires the original cases and repetitions")
        if asdict(limits) != prior["limits"]:
            raise ValueError("Resume requires the original limits")
    elif selected_cases:
        cases = [case for case in cases if case["name"] in selected_cases]
        if set(selected_cases) != {case["name"] for case in cases}:
            raise ValueError("A selected case does not exist")
    if pilot is not None:
        # Include every family rather than only the first corpus.
        rng = random.Random(20261110)
        rng.shuffle(cases)
        cases = cases[:pilot]
    if len(cases) * repetitions * 2 > limits.max_episodes:
        raise ValueError("Planned episodes exceed --max-episodes; no inference started")
    async with get_db_session():
        llm = await llm_service.get_profile_llm(model_usages.EXECUTOR)
        if llm is None:
            raise ValueError("Configure an executor model before running the benchmark")
        model_id = llm.id
        model_name = llm.llm_name
        binding = model_binding(llm)
        effort = await llm_service.get_profile_reasoning_effort_for_agent_id(model_usages.EXECUTOR, None)
        common = await params_service.get_or_default(Params.AI_GALARIS_OPERATING_PROMPT) or ""
        action_policy = await params_service.get_or_default(Params.AI_CONVERSATION_ACTION_POLICY) or ""
        suffixes = {kind: await params_service.get(name) or "" for kind, name in (
            ("task", Params.AI_EXECUTOR_SYSTEM_PROMPT),
            ("conversation", Params.AI_CONVERSATION_EXECUTOR_SYSTEM_PROMPT),
            ("voice", Params.AI_VOICE_EXECUTOR_SYSTEM_PROMPT))}
    if not common.strip():
        raise ValueError("The candidate operating prompt is empty; no treatment to measure")

    frozen: dict[str, dict[str, str]] = json.loads((output / "prompts.json").read_text()) if resume else {}
    if prior is not None:
        if (digest(frozen) != prior["prompts_sha256"] or model_id != prior["model_id"]
                or model_name != prior["model"] or effort != prior["reasoning_effort"]
                or (prior.get("model_binding") is not None and binding != prior["model_binding"])):
            raise ValueError("Frozen prompts or candidate binding changed")
    for case in ([] if resume else cases):
        definition = get_mechanism(case["mechanism"])
        kind = cast(ExecutorKind, definition.executor)
        baseline = suffixes[kind]
        candidate = "\n\n".join(value.strip() for value in (common, baseline) if value.strip())
        frozen[case["key"]] = {}
        for variant, suffix in (("before", baseline), ("after", candidate)):
            _, text = build_executor_benchmark_prompt(definition, case["native"], suffix=suffix,
                                                     conversation_action_policy=action_policy)
            frozen[case["key"]][variant] = text
        # Every positive oracle must accept its own reference before a paid call.
        failed = ([check for check in case_checks(case, case["expected"]) if not check["passed"]]
                  if not case["key"].startswith("latency_") else [])
        if failed:
            raise ValueError(f"Invalid frozen reference: {case['key']}: {failed}")

    output.mkdir(parents=True, exist_ok=resume)
    planned = len(cases) * repetitions * 2
    manifest = {"version": "galaris-operating-prompt-benchmark/v1", "model": model_name,
        "model_id": model_id, "model_binding": binding, "reasoning_effort": effort, "repetitions": repetitions,
        "case_count": len(cases), "planned": planned, "limits": asdict(limits),
        "selected_cases": selected_cases,
        "cases_sha256": digest(cases), "prompts_sha256": digest(frozen),
        "builder_sha256": hashlib.sha256((ROOT / "app/agent/executor_prompts.py").read_bytes()).hexdigest(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "operating_prompt_sha256": digest(common), "baseline_suffixes": suffixes,
        "conversation_action_policy": action_policy,
        "order": "Deterministic shuffled pairs, alternated arm order, sequential arms per pair",
        "executed": execute}
    if prior is None:
        for name, value in (("manifest", manifest), ("cases", cases), ("prompts", frozen)):
            (output / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2))
    else:
        with (output / "resumptions.jsonl").open("a") as stream:
            stream.write(json.dumps({"script_sha256": manifest["script_sha256"], "model_binding": binding,
                                     "original_binding_available": "model_binding" in prior}) + "\n")
        if (output / "summary.json").exists():
            (output / f"summary-before-resume-{time.time_ns()}.json").write_bytes((output / "summary.json").read_bytes())
    if not execute:
        return manifest

    results: list[dict[str, Any]] = ([json.loads(line) for line in (output / "results.jsonl").read_text().splitlines()]
                                   if resume and (output / "results.jsonl").exists() else [])
    completed = {(row["case"], row["repetition"], row["variant"]) for row in results}
    if len(completed) != len(results):
        raise ValueError("Duplicate published observations; refuse resume")
    if resume and any(row["cost"]["unknown_calls"] or row["cost"]["running_calls"] for row in results):
        raise ValueError("Reconcile unknown or running costs before resuming")
    queue: asyncio.Queue[tuple[dict[str, Any], int, list[str]]] = asyncio.Queue()
    rng = random.Random(20261110)
    for repetition in range(1, repetitions + 1):
        ordered = list(cases)
        rng.shuffle(ordered)
        for index, case in enumerate(ordered):
            variants = ["before", "after"] if (index + repetition) % 2 else ["after", "before"]
            variants = [variant for variant in variants if (case["key"], repetition, variant) not in completed]
            if variants:
                queue.put_nowait((case, repetition, variants))
    stop_reasons: set[str] = set()
    cost = sum(row["cost"]["recorded_cost"] for row in results)

    async def worker() -> None:
        nonlocal cost
        while not queue.empty() and not stop_reasons:
            case, repetition, variants = queue.get_nowait()
            for variant in variants:
                if cost >= limits.max_cost:
                    stop_reasons.add("cost_threshold")
                if stop_reasons:
                    break
                row: dict[str, Any] = {"case": case["key"], "name": case["name"], "categories": case["categories"],
                    "mechanism": case["mechanism"], "repetition": repetition, "variant": variant, "passed": False}
                started = time.monotonic()
                with llm_call_accounting() as accounting:
                    try:
                        async with get_db_session():
                            model = await llm_service.get_llm(model_id)
                            if model is None:
                                raise ValueError("Frozen candidate model disappeared")
                            if model_binding(model) != binding:
                                raise ValueError("Frozen candidate model binding changed")
                            with reasoning_effort_scope(effort):
                                async with asyncio.timeout(limits.timeout_seconds):
                                    observations: dict[str, Any] = {}
                                    actual, _ = await evaluate_mechanism(get_mechanism(case["mechanism"]),
                                        input_data=case["native"], llm=model,
                                        system_prompt_override=frozen[case["key"]][variant], observations=observations)
                            checks = case_checks(case, actual)
                            row.update(output=actual, checks=checks, passed=all(check["passed"] for check in checks),
                                       tool_calls_count=len(actual.get("tool_calls", [])), performance=observations)
                    except Exception as error:
                        row["error_type"] = type(error).__name__
                        row["error_kind"] = "model_behavior" if model_failure(error) else "infrastructure"
                        row["error_locations"] = [{"file": Path(frame.filename).name, "line": frame.lineno,
                                                   "function": frame.name} for frame in traceback.extract_tb(error.__traceback__)[-5:]]
                        # Argument/retry limits are model behaviour. Infrastructure failures
                        # stop admission, preserving all completed and in-flight evidence.
                        if not model_failure(error):
                            stop_reasons.add("infrastructure_error")
                    finally:
                        summary = accounting.snapshot()
                        row["cost"] = summary.model_dump(mode="json", exclude={"entries"})
                        cost += summary.recorded_cost
                        if summary.unknown_calls or summary.running_calls:
                            stop_reasons.add("unknown_or_running_cost")
                row["seconds"] = time.monotonic() - started
                results.append(row)
                with (output / "results.jsonl").open("a") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                (output / "progress.json").write_text(json.dumps({"completed": len(results), "planned": planned,
                    "recorded_cost_usd": cost, "stop_reasons": sorted(stop_reasons)}))
                print(json.dumps({"completed": len(results), "planned": planned, "case": case["name"],
                    "variant": variant, "passed": row["passed"], "error": row.get("error_type"),
                    "recorded_cost_usd": round(cost, 6)}), flush=True)

    await asyncio.gather(*(worker() for _ in range(limits.concurrency)))
    report = aggregate(results, planned=planned)
    report["stop_reasons"] = sorted(stop_reasons)
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cost", type=float, required=True)
    parser.add_argument("--max-episodes", type=int, default=600)
    parser.add_argument("--repetitions", type=int, choices=range(3, 21), default=3)
    parser.add_argument("--concurrency", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--timeout-seconds", type=float, default=180)
    parser.add_argument("--pilot", type=int)
    parser.add_argument("--case", action="append", dest="selected_cases", help="Restrict a focused follow-up to named scenarios")
    parser.add_argument("--run", action="store_true", help="Execute paid inferences; otherwise freeze a plan only")
    parser.add_argument("--rescore", action="store_true", help="Recheck an existing local evidence directory without inference")
    parser.add_argument("--resume", action="store_true", help="Run only missing episodes from frozen local evidence")
    args = parser.parse_args()
    if (not math.isfinite(args.max_cost) or args.max_cost <= 0 or args.max_episodes <= 0
            or not math.isfinite(args.timeout_seconds) or args.timeout_seconds <= 0
            or (args.pilot is not None and args.pilot <= 0)):
        parser.error("Budgets, timeout and pilot size must be positive")
    logger.remove()
    if args.rescore:
        print(json.dumps(rescore(args.output), ensure_ascii=False, indent=2))
        return
    report = await benchmark(args.output, repetitions=args.repetitions,
        limits=Limits(args.max_cost, args.max_episodes, args.concurrency, args.timeout_seconds),
        execute=args.run, pilot=args.pilot, resume=args.resume, selected_cases=args.selected_cases)
    print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
