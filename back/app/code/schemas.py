from datetime import datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .contracts import Mode


class WorkspaceInfo(BaseModel):
    id: UUID
    uri: str
    label: str
    mode: Mode


class SessionRequest(BaseModel):
    mode: Mode | None = None
    file: str | None = Field(default=None, max_length=1024)
    view: Literal["files", "changes"] | None = None

    @field_validator("file")
    @classmethod
    def relative_file(cls, value: str | None) -> str | None:
        if value is not None and (PurePosixPath(value).is_absolute() or ".." in PurePosixPath(value).parts
                                  or "\\" in value or any(ord(char) < 32 for char in value)):
            raise ValueError("file must be a relative repository path")
        return value


class SessionInfo(BaseModel):
    id: UUID
    workspace: WorkspaceInfo
    url: str
    expires_at: datetime


class HeartbeatInfo(BaseModel):
    state: Literal["ready"] = "ready"
    workspace: WorkspaceInfo


class RecoveryInfo(HeartbeatInfo):
    restart_required: bool = False
    url: str | None = None
