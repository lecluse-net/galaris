"""Public controls and progress for private file acquisition."""

from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class FileIndexRequest(BaseModel):
    agent_id: int
    root_uri: str = Field(min_length=3, max_length=2048)
    max_entries: int = Field(default=100000, ge=1, le=1000000)
    max_depth: int = Field(default=64, ge=0, le=64)


class FileIndexProgress(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    agent_id: int
    root_uri: str
    status: Literal["queued", "running", "retry", "success", "partial", "error", "excluded", "cancelled"]
    scanned: int
    directories: int
    max_entries: int
    max_depth: int
    attempts: int
    error_type: str | None
    started_at: datetime
    updated_at: datetime
    next_attempt_at: datetime


class FileIndexPage(BaseModel):
    runs: list[FileIndexProgress]
    total: int
    pending_repairs: int
    failed_repairs: int
