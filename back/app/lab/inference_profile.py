"""Non-secret identity checks for frozen inference bindings."""

import hashlib
import json
from typing import Any
from app.llm import LLM


def model_binding(llm: LLM) -> str:
    value = {
        "model": llm.llm_name,
        "provider": llm.llm_provider_id,
        "endpoint": llm.provider.base_url,
        "configuration": llm.provider.configuration,
        "capabilities": llm.service_capabilities,
    }
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def validate_binding(llm: LLM, snapshot: dict[str, Any]) -> None:
    if snapshot.get("binding") != model_binding(llm):
        raise ValueError("Model binding changed after capture; create a new benchmark")


def benchmark_fingerprints(
    cases: list[dict[str, Any]],
    configuration: dict[str, Any],
    candidate: dict[str, Any],
    judge: dict[str, Any],
) -> dict[str, str]:
    """Compare corpus, context and model bindings independently."""

    def digest(value: object) -> str:
        return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()

    context_configuration = {
        key: value
        for key, value in configuration.items()
        if key
        not in {
            "dataset_id",
            "dataset_revision",
            "dataset_name",
            "rubric",
            "judge_reasoning_effort",
            "fingerprints",
        }
    }
    if isinstance(context_configuration.get("algorithm"), dict):
        context_configuration["algorithm"] = {
            key: value
            for key, value in context_configuration["algorithm"].items()
            if key not in {"rubric", "judge_inference"}
        }
    return {
        "corpus": digest(
            [
                {
                    "variable": item["input_data"]["variable_value"],
                    "context": item["input_data"].get("context", {}),
                    "expected": item["expected_output"],
                }
                for item in cases
            ]
        ),
        "context": digest(
            {
                "parameters": configuration.get("parameters", {}),
                "configuration": context_configuration,
            }
        ),
        "candidate": digest(
            {
                "binding": candidate["binding"],
                "reasoning": [case.get("reasoning_effort") for case in cases],
            }
        ),
        "judge": digest(
            {
                "binding": judge.get("binding"),
                "rubric": configuration.get("rubric"),
                "reasoning": configuration.get("judge_reasoning_effort"),
            }
        ),
    }
