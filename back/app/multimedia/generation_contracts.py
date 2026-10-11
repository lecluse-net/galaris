"""State and results of a media generation."""
from typing import Any, Literal
from pydantic import BaseModel

class MediaGenerationError(BaseModel):
    code: str
    message: str

class MediaGenerationSnapshot(BaseModel):
    status: Literal["queued", "running", "waiting", "cancelling", "success", "error", "cancelled", "unknown"]
    output: dict[str, Any] | None = None
    error: MediaGenerationError | None = None
