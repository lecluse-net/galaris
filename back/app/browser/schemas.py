"""Typed contracts shared with the isolated browser executor."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

BrowserOutput = Literal["content", "screenshot"]
ImageFormat = Literal["jpeg", "png"]


class BrowserOwner(BaseModel):
    agent_id: int | None = Field(default=None, gt=0)
    user_id: int | None = Field(default=None, gt=0)
    task_id: str | None = None

    @model_validator(mode="after")
    def one_identity(self) -> BrowserOwner:
        if (self.agent_id is None) == (self.user_id is None):
            raise ValueError("Exactly one browser owner is required")
        if self.user_id is not None and self.task_id is not None:
            raise ValueError("Human previews cannot claim an Agent task")
        return self


class BrowserPageBase(BaseModel):
    session_id: str
    url: str
    title: str
    description: str = ""
    site_name: str = ""
    revision: int = Field(ge=0)


class BrowserPageMetadata(BaseModel):
    title: str = ""
    description: str = ""
    site_name: str = ""


class BrowserContent(BrowserPageBase):
    content: str
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    total: int = Field(ge=0)
    truncated: bool
    next_offset: int | None = Field(default=None, ge=0)


class BrowserScreenshotPart(BaseModel):
    index: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    mime_type: Literal["image/jpeg", "image/png"]
    data: str


class BrowserScreenshot(BrowserPageBase):
    page_width: int = Field(gt=0)
    page_height: int = Field(gt=0)
    captured_height: int = Field(ge=0)
    truncated: bool
    parts: list[BrowserScreenshotPart]


class BrowserClosed(BaseModel):
    closed: bool
    session_id: str


class BrowserOwnerClosed(BaseModel):
    closed: int = Field(ge=0)
