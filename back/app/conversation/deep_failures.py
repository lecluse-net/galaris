"""Room-safe diagnostics for current and historic Deep executions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.agent.contracts import HarnessFailure
from core.database import get_db
from core.failure_journal import read_taskless_run_failures

from .models import DeepEvent, DeepSubmission


DeepFailureCode = Literal[
    "skills", "skills_task_required", "access", "http", "configuration", "unavailable", "protocol", "quota",
    "timeout", "cancelled", "effect_unknown", "runtime", "unrecorded",
]
_HARNESS_HTTP = re.compile(r"Harness HTTP request failed \(([45][0-9]{2})\)\.")


class DeepFailureInfo(BaseModel):
    code: DeepFailureCode
    http_status: int | None = Field(default=None, ge=400, le=599)


def describe_deep_failure(
    failure: HarnessFailure | None = None, *, error_type: str = "", message: str = "",
) -> DeepFailureInfo:
    """Project a bounded reason without copying exception text into the Chat."""
    if error_type == "PermissionError":
        return DeepFailureInfo(code="access")
    if "Skill synchronization requires an admitted Task." in message:
        return DeepFailureInfo(code="skills_task_required")
    if "Skill synchronization " in message or "Skills changed during synchronization" in message:
        return DeepFailureInfo(code="skills")
    match = _HARNESS_HTTP.search(failure.message if failure is not None else message)
    if match is not None:
        return DeepFailureInfo(code="http", http_status=int(match.group(1)))
    return DeepFailureInfo(code=failure.code if failure is not None else "runtime")


async def read_deep_failures(submissions: Sequence[DeepSubmission]) -> dict[UUID, DeepFailureInfo]:
    failed_ids = {item.id for item in submissions if item.state == "failed"}
    if not failed_ids:
        return {}
    rows = await get_db().execute(select(DeepEvent.submission_id, DeepEvent.payload)
        .where(DeepEvent.kind == "failure", DeepEvent.submission_id.in_(failed_ids))
        .order_by(DeepEvent.sequence.desc()))
    failures: dict[UUID, DeepFailureInfo] = {}
    for submission_id, payload in rows:
        try:
            failures.setdefault(submission_id, DeepFailureInfo.model_validate(payload))
        except ValidationError:
            continue
    pending = failed_ids.difference(failures)
    history = await read_taskless_run_failures(pending)
    for submission_id in pending:
        evidence = history.get(submission_id)
        failures[submission_id] = (describe_deep_failure(error_type=evidence.error_type, message=evidence.message)
                                   if evidence is not None else DeepFailureInfo(code="unrecorded"))
    return failures
