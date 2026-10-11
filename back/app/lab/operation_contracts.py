"""State and results of a Lab operation."""
from typing import Any, Literal
from pydantic import BaseModel

Operation = Literal[
    "lab_dataset_generate", "lab_expected_generate", "lab_run_analyze", "lab_task_analyze"
]

class LabOperationError(BaseModel):
    code: str
    message: str

class LabOperationSnapshot(BaseModel):
    status: Literal["queued", "running", "waiting", "cancelling", "success", "error", "cancelled", "unknown"]
    output: dict[str, Any] | None = None
    error: LabOperationError | None = None
