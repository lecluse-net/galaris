"""Inject reviewed faults in disposable copies; require behavioral test failures."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from defusedxml.ElementTree import parse


@dataclass(frozen=True)
class Mutation:
    name: str
    source: str
    before: str
    after: str
    tests: tuple[str, ...]


CALLBACK_TEST = "app/process/tests/test_recovery.py::test_callback_completion_resumes_wait_once_and_survives_redelivery"
WORKFLOW_TESTS = ("app/task/tests/test_workflow.py", "-k", "generated_event_sequences or typed_workflow_covers")
MUTATIONS = (
    Mutation("harness-orphan-blind-replay", "app/task/scheduler.py",
             'if (task.data or {}).get("_agent_run_identity") is not None:', 'if False:',
             ("app/task/tests/test_scheduler.py::test_orphan_recovery_is_side_effect_and_history_safe[False]",)),
    Mutation("harness-accepts-post-terminal-event", "app/agent/driver_stream.py",
             'if terminal is not None:\n                raise HarnessProtocolError',
             'if False:\n                raise HarnessProtocolError',
             ("app/agent/tests/test_driver_boundary.py::test_generated_event_sequences_admit_only_one_clean_terminal",)),
    Mutation("harness-shares-mutable-request", "app/agent/driver_stream.py",
             'deepcopy(getattr(request, item.name))', 'getattr(request, item.name)',
             ("app/agent/tests/test_driver_boundary.py::test_mutating_driver_cannot_change_caller_or_previously_yielded_event",)),
    Mutation("harness-ignores-operator-policy", "app/agent/capabilities.py",
             'configured = supported - settings.disabled_capabilities', 'configured = supported',
             ("app/harnesses/tests/test_execution_configuration.py::test_capability_negotiation_cannot_invent_or_disable_guarantees",)),
    Mutation("mcp-timeout-treated-as-rejection", "app/harness/checkpoint.py",
             '"rejected" if execution.outcome == "rejected"\n'
             '                                    or effect_policy == "read" else "unknown"',
             '"rejected"',
             ("app/harness/tests/test_execution_evidence.py",)),
    Mutation("provider-sdk-ignores-thinking-tool-restriction", "app/llm/pydantic_ai_utils.py",
             "openai_supports_forced_tool_choice_with_thinking=False,",
             "openai_supports_forced_tool_choice_with_thinking=True,",
             ("tests/test_provider_parameters.py::test_sdk_inference_composes_with_provider_contract[tool-None-deepseek-deepseek-v4-pro-responses]",)),
    Mutation("late-start-failure-overwrites-callback", "app/process/process_service.py",
             "if locked_run.status in TERMINAL_STATUSES:\n            # A callback",
             "if False:\n            # A callback",
             ("app/process/tests/test_lifecycle_workflows.py::test_lost_start_response_cannot_overwrite_a_terminal_callback",)),
    Mutation("late-start-ack-overwrites-callback", "app/process/process_service.py",
             "if locked_run.status not in TERMINAL_STATUSES:\n                locked_run.engine_run_id",
             "if True:\n                locked_run.engine_run_id",
             ("app/process/tests/test_lifecycle_workflows.py::test_lost_start_response_cannot_overwrite_a_terminal_callback",)),
    Mutation("dbadmin-issues-before-parent", "core/dbadmin/journal.py",
             "        await session.flush()\n        session.add_all(", "        session.add_all(",
             ("core/dbadmin/tests/test_operator_guarantees.py::test_operator_summary_is_bounded_and_returns_latest_persisted_verdict",)),
    Mutation("concurrent-discovery-uses-expired-owner", "app/process/process_service.py",
             "ProcessRun.engine_code == engine_code,\n                    ProcessRun.engine_run_id == engine_run_id,",
             "ProcessRun.engine_code == tool.code,\n                    ProcessRun.engine_run_id == engine_run_id,",
             ("app/process/tests/test_worker_concurrency.py::test_parallel_external_execution_discovery_creates_one_canonical_run",)),
    Mutation("invalid-transition-accepted", "app/task/workflow.py",
             "if task.status not in rule.sources:", "if False:", WORKFLOW_TESTS),
    Mutation("terminal-collaboration-reopened", "app/task/workflow.py",
             "frozenset({TaskStatus.DISPATCH}),\n        TaskStatus.DISPATCH,",
             "frozenset({TaskStatus.DISPATCH, TaskStatus.SUCCESS, TaskStatus.ERROR}),\n        TaskStatus.DISPATCH,", WORKFLOW_TESTS),
    Mutation("child-budget-overrun", "core/util/byte_budget.py",
             "parent.available >= total", "True", ("core/util/tests/test_byte_budget.py",)),
    Mutation("duplicate-runtime-start", "core/runtime.py",
             "if not state.pending.done():\n                return", "if False:\n                return",
             ("core/tests/test_runtime_timeouts.py",)),
    Mutation("callback-auth-bypassed", "app/process/process_service.py",
             'if not secrets.compare_digest(token or "", run.callback_token):\n        metrics.increment',
             'if False:\n        metrics.increment', (CALLBACK_TEST,)),
    Mutation("terminal-result-overwritten", "app/process/process_service.py",
             "accepted = run.status not in TERMINAL_STATUSES and can_transition(run.status, target)",
             "accepted = can_transition(run.status, target)", (CALLBACK_TEST,)),
    Mutation("duplicate-callback-replayed", "app/process/process_service.py",
             'if duplicate is not None:\n        metrics.increment',
             'if False:\n        metrics.increment', (CALLBACK_TEST,)),
    Mutation("stale-worker-publishes", "app/lab/run_publication.py",
             'run is None or run.lease_token != token or run.status != "running"',
             'run is None or run.status != "running"',
             ("app/lab/tests/test_run_publication.py::test_publication_observes_concurrent_control[replace_lease]",)),
    Mutation("task-reservation-ignored", "app/task/budget.py",
             "tokens + (active + 1) * token_reserve > limits.TASK_ROOT_MAX_TOKENS",
             "tokens > limits.TASK_ROOT_MAX_TOKENS",
             ("app/task/tests/test_budget.py::test_causal_descendants_share_accounting_and_lease_reservations",)),
)


def main() -> None:
    if os.environ.get("APP_ENV") != "test" or os.environ.get("POSTGRES_DB") != "test_db":
        raise RuntimeError("Use make tests-mutations with its isolated PostgreSQL database")
    source = Path(__file__).resolve().parents[1]
    report = Path(os.environ.get("MUTATION_REPORT", "/repo/artifacts/mutations.json"))
    results: list[dict[str, object]] = []
    try:
        for mutation in MUTATIONS:
            with tempfile.TemporaryDirectory(prefix="galaris-mutation-") as temporary:
                root = Path(temporary) / "back"
                shutil.copytree(source, root, ignore=shutil.ignore_patterns(
                    ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".coverage",
                ))
                path = root / mutation.source
                content = path.read_text()
                if content.count(mutation.before) != 1:
                    raise RuntimeError(f"Mutation anchor changed: {mutation.name}; review the fault")
                evidence: dict[str, object] = {
                    "name": mutation.name, "tests": mutation.tests, "detected": False,
                    "source_sha256": hashlib.sha256(content.encode()).hexdigest(),
                    "test_sha256": hashlib.sha256((root / mutation.tests[0].split("::")[0]).read_bytes()).hexdigest(),
                }
                results.append(evidence)
                for modified in (False, True):
                    if modified:
                        path.write_text(content.replace(mutation.before, mutation.after))
                        for cache in root.rglob("__pycache__"):
                            shutil.rmtree(cache)
                    junit = Path(temporary) / "result.xml"
                    outcome = subprocess.run(
                        [sys.executable, "-m", "pytest", *mutation.tests, "-q", f"--junitxml={junit}"],
                        cwd=root, env={**os.environ, "PYTHONPATH": str(root)},
                        capture_output=True, text=True, timeout=180,
                    )
                    suites = parse(junit).getroot() if junit.exists() else ET.Element("missing")
                    assert suites is not None
                    cases = suites.findall(".//testcase")
                    failures = suites.findall(".//failure")
                    behavioral = any(
                        row.get("type", "").endswith(("AssertionError", "Failed"))
                        or row.get("message", "").startswith(("AssertionError", "assert ", "Failed:"))
                        for row in failures
                    )
                    valid = bool(cases) and not suites.findall(".//error") and not suites.findall(".//skipped")
                    expected = outcome.returncode == (1 if modified else 0)
                    if not valid or not expected or (modified and not behavioral):
                        raise RuntimeError(f"Invalid {'mutation' if modified else 'baseline'}: {mutation.name}\n"
                                           + outcome.stdout + outcome.stderr)
                    if modified:
                        evidence["detected"] = True
                        evidence["failures"] = [row.get("name") for row in cases if row.find("failure") is not None]
                print(f"{mutation.name}: verified", flush=True)
    finally:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(json.dumps({"version": 1, "expected": len(MUTATIONS), "mutations": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
