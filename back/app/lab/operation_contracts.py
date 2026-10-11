"""State and results of a Lab operation."""
from typing import Any, Literal
from pydantic import BaseModel

class LabOperationError(BaseModel):
    code: str
    message: str

class LabOperationSnapshot(BaseModel):
    status: Literal["queued", "running", "waiting", "cancelling", "success", "error", "cancelled", "unknown"]
    output: dict[str, Any] | None = None
    error: LabOperationError | None = None
