"""Development-only semantic trial of the real Process input assessor, without business effects.

Uses the configured conversation model and entirely synthetic cases. No Process run,
conversation, document or memory is created. Provider calls retain normal LLM accounting.
This complements DB/browser orchestration tests; it is not a full live controller journey.
"""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
import time
from typing import Any


def synthetic_cases() -> list[dict[str, Any]]:
    birth = {"name": "birth", "label": "Beneficiary birth date", "description": "Birth date of the beneficiary, not the requester.", "type": "date", "nullable": False}
    defaults: dict[str, Any] = {"language": "fr", "current_messages": [], "history": [], "previous_dossier": None,
        "proposed_values": {}, "recent_actual_runs": [], "input_contract": {"workflow_id": "synthetic-registration", "declarations": [birth], "missing": ["birth"], "values": {}}}
    previous: dict[str, Any] = {"request": "Lance mon inscription", "launch_requested": True, "status": "collecting", "values": {}}
    scenarios: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = [
            ("beneficiary", "Lance l’inscription du bénéficiaire. Je suis né le 1980-06-15, le bénéficiaire le 2000-02-29.", {},
                {"action": "collect", "launch_requested": True, "single_launch": True, "values": {"birth": "2000-02-29"}}),
            ("missing", "Lance l’inscription ; je fournirai la date de naissance plus tard.", {},
                {"action": "collect", "launch_requested": True, "absent": ["birth"]}),
            ("cancel", "Annule cette inscription, ne la lance pas.", {"previous_dossier": previous},
                {"action": "cancel", "launch_requested": False, "single_launch": False}),
            ("unrelated", "Au fait, explique-moi la formation des aurores boréales.", {"previous_dossier": previous},
                {"action": "unrelated", "single_launch": False}),
            ("ambiguous_date", "Lance l’inscription. La naissance est le 03/04/2000, je ne connais pas la convention utilisée.", {},
                {"action": "collect", "absent": ["birth"], "question_required": True}),
            ("multiple", "Lance deux inscriptions identiques pour le bénéficiaire né le 2000-02-29.", {},
                {"action": "collect", "launch_requested": True, "single_launch": False}),
            ("no_consent", "Explique seulement ce que ferait l’inscription du bénéficiaire né le 2000-02-29, sans la lancer.", {},
                {"launch_requested": False, "single_launch": False}),
            ("conflicting_sources", "Lance l’inscription. Deux documents du même bénéficiaire indiquent respectivement 2000-02-29 et 2001-03-01 ; je ne sais pas lequel est correct.", {},
                {"action": "collect", "absent": ["birth"], "question_required": True}),
        ]
    return [{"name": name, "input": {**defaults, **changes, "current_human_message": message}, "expected": expected}
        for name, message, changes, expected in scenarios]


def expectation_errors(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for field in ("action", "launch_requested", "single_launch"):
        if field in expected and actual.get(field) != expected[field]:
            errors.append(field)
    for name, value in expected.get("values", {}).items():
        if actual.get("values", {}).get(name) != value:
            errors.append("values." + name)
    for name in expected.get("absent", []):
        if name in actual.get("values", {}):
            errors.append("invented_or_ambiguous." + name)
    if expected.get("question_required") and not str(actual.get("question", "")).strip():
        errors.append("question")
    return errors


async def trial(output: Path, *, max_calls: int, llm_id: int | None = None) -> bool:
    from core.settings import settings
    if not settings.is_dev:
        raise ValueError("Real-model Process input trials require APP_ENV=dev")
    if output.exists():
        raise ValueError("Preserve existing trial evidence; choose a new output path")
    from pydantic import BaseModel
    from typing import cast
    from core.database import get_db_session, load_models
    from core.params import params_service
    from modules import load_llm_provider_modules
    from app.conversation.facade import process_input_evaluation_spec
    from app.llm import llm_service, model_usages, run_structured, reasoning_effort_scope, LLMCallPurpose

    load_models()
    load_llm_provider_modules()
    model, prompt = process_input_evaluation_spec()
    cases = synthetic_cases()[:max_calls]
    results: list[dict[str, Any]] = []
    async with get_db_session():
        await params_service.load_params()
        llm = await llm_service.get_llm(llm_id) if llm_id is not None else await llm_service.get_profile_llm(model_usages.CONVERSATION)
        if llm is None:
            raise ValueError("Configure a conversation model or select an existing --llm-id")
        for case in cases:
            started = time.monotonic()
            try:
                with reasoning_effort_scope("none"):
                    async with asyncio.timeout(45):
                        inference = await run_structured(llm=llm, output_type=cast(type[BaseModel], model), system_prompt=prompt,
                            prompt=json.dumps(case["input"], ensure_ascii=False), task_id=None, agent_id=None,
                            temperature=0.0, request_limit=1, output_retries=0, count_tokens_before_request=False,
                            purpose=LLMCallPurpose.LAB_MECHANISM_RUN, model_field=model_usages.CONVERSATION)
                actual = inference.output.model_dump(mode="json")
                errors = expectation_errors(actual, case["expected"])
                results.append({"case": case["name"], "passed": not errors, "errors": errors,
                    "actual": actual, "seconds": round(time.monotonic() - started, 3), "cost": inference.cost})
            except Exception as error:
                # Persist safe error identity, never credentials, endpoints or provider payloads.
                results.append({"case": case["name"], "passed": False, "error_type": type(error).__name__,
                    "seconds": round(time.monotonic() - started, 3)})
    success = all(case["passed"] for case in results)
    report = {"version": "process-input-semantic-trial/v1", "synthetic": True,
        "scope": "Production input assessment prompt/output against a real configured model; no controller tools or business execution",
        "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        "suite_sha256": hashlib.sha256(json.dumps(cases, sort_keys=True).encode()).hexdigest(),
        "model": llm.code, "passed": success, "results": results}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return success


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-calls", type=int, choices=range(1, 9), default=8)
    parser.add_argument("--llm-id", type=int)
    args = parser.parse_args()
    raise SystemExit(0 if asyncio.run(trial(args.output, max_calls=args.max_calls, llm_id=args.llm_id)) else 1)


if __name__ == "__main__":
    main()
