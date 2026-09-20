"""HTTP schemas for generic harness supervision."""

from pydantic import BaseModel

from .contracts import HarnessCapability


class HarnessRuntimeState(BaseModel):
    status: str
    capabilities: list[HarnessCapability]


class HarnessActionResult(BaseModel):
    status: str
    output: str = ""


class HarnessLogs(BaseModel):
    lines: list[str]
