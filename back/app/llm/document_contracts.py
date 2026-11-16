"""Technical analysis snapshots, independent of business processes."""

from typing import Any, Literal

from pydantic import BaseModel
from uuid import UUID


def same_source_content_version(expected: dict[str, Any], current: dict[str, Any]) -> bool:
    """Metadata timestamps cannot invalidate an explicit content identity.

    Preserve timestamp checks for providers exposing no revision or checksum, and
    keep the originally admitted snapshot intact for diagnostics and evidence.
    """
    def content_version(version: dict[str, Any]) -> dict[str, Any]:
        if version.get("revision") is not None or version.get("checksum"):
            return {key: value for key, value in version.items() if key != "modified_at"}
        return version

    return content_version(expected) == content_version(current)

DocumentAnalysisStatus = Literal["queued", "running", "cancelling", "success", "error", "cancelled", "unknown"]


class DocumentAnalysisError(BaseModel):
    code: str
    message: str
    phase: str | None = None
    cause_type: str | None = None
    http_status: int | None = None
    locations: list[str] | None = None
    preparation: dict[str, Any] | None = None


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
