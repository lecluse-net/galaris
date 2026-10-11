"""Technical analysis snapshots, independent of business processes."""

from typing import Any, Literal

from pydantic import BaseModel
from uuid import UUID

DocumentAnalysisStatus = Literal["queued", "running", "cancelling", "success", "error", "cancelled", "unknown"]


class DocumentAnalysisError(BaseModel):
    code: str
    message: str


class DocumentAnalysisSnapshot(BaseModel):
    status: DocumentAnalysisStatus
    output: dict[str, Any] | None = None
    error: DocumentAnalysisError | None = None


class AcquiredDocumentEvidence(BaseModel):
    """Previously paid evidence, with coverage and the admitted source version."""

    analysis_id: UUID
    uri: str
    version: dict[str, Any]
    coverage: dict[str, Any]
    passages: list[dict[str, Any]]
    answer: str
