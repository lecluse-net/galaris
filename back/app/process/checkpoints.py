"""Validate durable launch data before any external execution or file access."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from .schemas import ProcessFileRef


class LaunchSnapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    # Missing version and optional values are accepted for historical runs.
    version: Literal[1] = 1
    workflow_id: str = ""
    process_label: str = ""
    tool_code: str = ""
    input: dict[str, Any] = Field(default_factory=dict)
    files: list[ProcessFileRef] = Field(default_factory=lambda: list[ProcessFileRef]())

    @field_validator("input", "files", mode="before")
    @classmethod
    def historical_null(cls, value: object, info: ValidationInfo) -> object:
        if value is None:
            return [] if info.field_name == "files" else {}
        return value
