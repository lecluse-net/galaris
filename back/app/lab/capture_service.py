"""Compare captured context with the dataset before adding an item."""

import hashlib
import json
from typing import Any, cast
from sqlalchemy import select
from core.database import get_db
from .contracts import LabInput, split_capture, validate_parameters
from .models import LabEvaluationCase, LabEvaluationDataset
from .mechanism_registry import get_mechanism


class CaptureParametersMismatch(Exception):
    def __init__(self, detail: dict[str, Any]) -> None:
        super().__init__("Captured parameters differ from the test dataset")
        self.detail = detail


async def check_capture(row: LabEvaluationCase, confirmation_token: str | None = None) -> None:
    with get_db().no_autoflush:
        dataset = await get_db().scalar(
            select(LabEvaluationDataset)
            .where(LabEvaluationDataset.id == row.dataset_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    if dataset is None:
        raise LookupError("Dataset not found")
    source = split_capture(dataset.mechanism, row.source_capture.get("input_data"))
    observed = validate_parameters(dataset.mechanism, source.parameters, partial=True)
    parameters = validate_parameters(dataset.mechanism, dataset.parameters)
    differences = [
        {"name": name, "source_value": value, "dataset_value": parameters[name]}
        for name, value in observed.items()
        if value != parameters[name]
    ]
    captured_prompts = row.source_capture.get("prompts")
    source_system_prompt = (
        cast(dict[str, Any], captured_prompts).get("system_prompt")
        if isinstance(captured_prompts, dict)
        else None
    )
    dataset_system_prompt = dataset.configuration.get(
        "system_prompt", get_mechanism(dataset.mechanism).system_prompt
    )
    if (
        isinstance(source_system_prompt, str)
        and source_system_prompt
        and source_system_prompt != dataset_system_prompt
    ):
        differences.append(
            {
                "name": "system_prompt",
                "scope": "configuration",
                "source_value": source_system_prompt,
                "dataset_value": dataset_system_prompt,
            }
        )
    if differences:
        evidence = {
            "dataset": str(dataset.id),
            "revision": dataset.revision,
            "input": row.input_data,
            "expected": row.expected_output,
            "parameters": parameters,
            "configuration": dataset.configuration,
            "differences": differences,
            "source_parameters": observed,
        }
        token = hashlib.sha256(
            json.dumps(evidence, sort_keys=True, default=str).encode()
        ).hexdigest()
        if confirmation_token != token:
            raise CaptureParametersMismatch(
                {
                    "code": "dataset_parameters_mismatch",
                    "dataset_id": str(dataset.id),
                    "dataset_name": dataset.name,
                    "differences": differences,
                    "confirmation_token": token,
                }
            )
        row.readiness = "draft"
        row.source_capture = {
            **row.source_capture,
            "parameter_confirmation": {
                "dataset_revision": dataset.revision,
                "differences": differences,
            },
        }
    row.input_data = LabInput.model_validate(row.input_data).model_dump(mode="json")
