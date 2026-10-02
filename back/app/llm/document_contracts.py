"""Technical analysis snapshots, independent of business processes."""

from typing import Any, Literal

from pydantic import BaseModel

DocumentAnalysisStatus = Literal["queued", "running", "cancelling", "success", "error", "cancelled", "unknown"]


class DocumentAnalysisError(BaseModel):
    code: str
    message: str


class DocumentAnalysisSnapshot(BaseModel):
    status: DocumentAnalysisStatus
    output: dict[str, Any] | None = None
    error: DocumentAnalysisError | None = None
