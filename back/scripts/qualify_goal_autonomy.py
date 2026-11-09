"""Bounded real-model Goal judgement trial on synthetic inputs, without business effects.

This qualifies decisions and tracking, not autonomous tool use or economic outcomes.
The same corpus may be run with an earlier prompt to compare behaviour.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
from typing import Any


def cases() -> list[dict[str, Any]]:
    return json.loads((Path(__file__).parents[1] / "app/lab/goal_autonomy_corpus.json").read_text())


async def trial(output: Path, *, max_cost: float, prompt_file: Path | None = None) -> bool:
    from core.settings import settings
    if not settings.is_dev:
        raise ValueError("Real-model Goal trials require APP_ENV=dev")
    if output.exists():
        raise ValueError("Preserve trial evidence; choose a new output path")
    from core.database import get_db_session, load_models
    from core.params import params_service
    from modules import load_llm_provider_modules
    from app.goal.facade import resolve_goal_tracking_system_prompt
    from app.goal.cycle_context import goal_judgement_runtime_instructions
    from app.goal.schemas import GoalJudgement
    from app.llm import llm_service, model_usages, run_structured, LLMCallPurpose

    load_models()
    load_llm_provider_modules()
    results: list[dict[str, Any]] = []
    total_cost = 0.0
    corpus = cases()
    async with get_db_session():
        await params_service.load_params()
        llm = await llm_service.get_profile_llm(model_usages.GOAL)
        if llm is None:
            raise ValueError("Configure the Goal tracking model before this trial")
        prompt = prompt_file.read_text() if prompt_file else await resolve_goal_tracking_system_prompt()
        for case in corpus:
            if total_cost >= max_cost:
                break
            message = (f"GOAL DESCRIPTION:\n{case['goal']}\nCURRENT DURABLE TRACKING (HTML):\n"
                       f"{case['tracking']}\nLATEST TASK STATUS: SUCCESS\nLATEST TASK RESULT:\n{case['result']}")
            if prompt_file is None:
                message += "\n\n" + goal_judgement_runtime_instructions()
            started = time.monotonic()
            try:
                async with asyncio.timeout(60):
                    inference = await run_structured(llm=llm, output_type=GoalJudgement,
                        system_prompt=prompt, prompt=message, task_id=None, agent_id=None,
                        temperature=0.0, request_limit=1, max_tokens=4000, output_retries=0,
                        count_tokens_before_request=False, purpose=LLMCallPurpose.LAB_MECHANISM_RUN,
                        model_field=model_usages.GOAL)
                total_cost += inference.cost
                actual = inference.output.model_dump(mode="json")
                results.append({"case": case["name"], "passed": actual["action"] in case["actions"],
                    "actual": actual, "cost": inference.cost, "seconds": time.monotonic() - started})
            except Exception as error:
                results.append({"case": case["name"], "passed": False,
                    "error_type": type(error).__name__, "seconds": time.monotonic() - started})
    success = len(results) == len(corpus) and total_cost <= max_cost and all(r["passed"] for r in results)
    report = {"version": "goal-autonomy-semantic-trial/v1", "synthetic": True,
        "scope": "Real-model judgement decisions; no autonomous tool or business execution",
        "comparison": "Prompt-only comparison under a common output schema, not an old-runtime benchmark",
        "model": llm.code, "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "corpus_sha256": hashlib.sha256(json.dumps(corpus, sort_keys=True).encode()).hexdigest(),
        "passed": success, "cost": total_cost, "max_cost": max_cost, "results": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return success


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-cost", type=float, default=1.0)
    parser.add_argument("--prompt-file", type=Path)
    args = parser.parse_args()
    if args.max_cost <= 0:
        parser.error("--max-cost must be positive")
    raise SystemExit(0 if asyncio.run(trial(args.output, max_cost=args.max_cost, prompt_file=args.prompt_file)) else 1)


if __name__ == "__main__":
    main()
