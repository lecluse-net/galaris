"""Public API schemas for SSH console administration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .contracts import ConsoleStatus


class ConsoleConnectionTest(BaseModel):
    connection_id: int
    status: ConsoleStatus


class ConsoleHelperInstallResult(BaseModel):
    connection_id: int
    path: str
    version: str
    status: ConsoleStatus


class GeneratedConsoleKey(BaseModel):
    connection_id: int
    public_key: str


class EmbeddedProvisionRequest(BaseModel):
    agent_id: int


class EmbeddedProvisionResult(BaseModel):
    connection_id: int
    agent_id: int
    agent_code: str
    public_key: str
    status: ConsoleStatus


class HostKeyScanRequest(BaseModel):
    host: str
    port: int = Field(default=22, ge=1, le=65535)


class HostKeyScanResult(BaseModel):
    host: str
    port: int
    key: str
    fingerprint: str


class ExecutorActionRequest(BaseModel):
    operation: str
    payload: dict[str, Any] = Field(default_factory=dict[str, Any])


class ExecutorAvailability(BaseModel):
    in_use: bool


class ExecutorResponse(BaseModel):
    ok: bool
    result: dict[str, Any] = Field(default_factory=dict[str, Any])
    error: str = ""
