"""Bounded, client-reported document attention attached to an internal message."""

from typing import Annotated, Literal, Self

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


class DocumentPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["point"]
    x: int = Field(ge=0, le=1_000_000, strict=True)
    y: int = Field(ge=0, le=1_000_000, strict=True)


class DocumentRectangle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["rectangle"]
    x: int = Field(ge=0, le=1_000_000, strict=True)
    y: int = Field(ge=0, le=1_000_000, strict=True)
    width: int = Field(ge=1, le=1_000_000, strict=True)
    height: int = Field(ge=1, le=1_000_000, strict=True)


class DocumentFocus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision: int = Field(ge=0)
    surface: Literal["rendered", "source", "dataset", "format", "history"]
    selection: DocumentTextRange | None = None
    cursor: DocumentCursor | None = None
    viewport: DocumentTextRange | None = None
    document_format: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$", max_length=80)
    anchor: Annotated[DocumentPoint | DocumentRectangle, Field(discriminator="kind")] | None = None

    @model_validator(mode="after")
    def validate_surface(self) -> Self:
        if self.surface in {"format", "history"}:
            if self.revision < 1 or self.document_format is None:
                raise ValueError("Format and history focus require a document format and saved revision")
            if self.selection is not None or self.cursor is not None or self.viewport is not None:
                raise ValueError("Format and history focus cannot include text coordinates")
        elif self.anchor is not None:
            raise ValueError("An anchor requires a format or history surface")
        return self
