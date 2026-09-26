"""Bounded, client-reported document attention attached to an internal message."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DocumentTextRange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str = Field(max_length=6000)
    truncated: bool = False

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.end < self.start:
            raise ValueError("Document range ends before its start")
        return self


class DocumentCursor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    offset: int = Field(ge=0)
    before: str = Field(max_length=160)
    after: str = Field(max_length=160)


class DocumentFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    surface: Literal["rendered", "source", "dataset"]
    selection: DocumentTextRange | None = None
    cursor: DocumentCursor | None = None
    viewport: DocumentTextRange | None = None
