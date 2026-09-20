"""Minimal schemas for n8n API responses."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class N8NWorkflow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    name: str
    active: bool = False
    nodes: list[dict[str, Any]] = Field(default_factory=lambda: [])


class N8NExecution(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    workflowId: Optional[str] = None
    status: Optional[str] = None
    finished: Optional[bool] = None
    data: Optional[dict[str, Any]] = None


class N8NConfigurationDefaults(BaseModel):
    galaris_base_url: str


class N8NConnectionTest(BaseModel):
    ok: bool
    code: str
    message: str = ""
