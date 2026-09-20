"""Versioned, backwards-compatible provider and delivery checkpoints."""

from typing import Literal
from pydantic import BaseModel, ConfigDict, Field


class OutputManifestEntry(BaseModel):
    external_id: str
    media_type: str
    url: str | None = None


class MultimediaCheckpoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Historical checkpoints without a version are v1. Future versions are
    # rejected for this run only, before any non-idempotent provider operation.
    multimedia_version: Literal[1] = 1
    submission: Literal["started", "accepted", "unknown"] | None = None
    provider_state: Literal["running", "waiting", "unknown", "success", "error"] | None = None
    external_id: str | None = None
    call_id: str | None = None
    output_count: int = Field(default=0, ge=0, le=4)
    output_manifest: list[OutputManifestEntry] = Field(
        default_factory=lambda: list[OutputManifestEntry](), max_length=4
    )
