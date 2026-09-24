"""Configurable Harness domain; the internal implementation remains ``app.harness``."""

from .contracts import (
    HarnessAction,
    HarnessCapability,
    HarnessCredentials,
    HarnessLifecycleStatus,
    HarnessProvider,
    HarnessProvisioningRequest,
    HarnessProvisioningResult,
    HarnessTarget,
)
from .facade import get_private_execution_credentials, resolve_agent_harness
from .openai_client import OpenAIHarnessClient
from .registry import all_providers, get_provider, register_provider
from .skill_sync import projected_skill_agent_ids, request_skill_sync
from . import agent_adapter as _agent_adapter  # noqa: F401 - registers the harness adapter # pyright: ignore[reportUnusedImport]

__all__ = [
    "HarnessAction",
    "HarnessCapability",
    "HarnessCredentials",
    "HarnessLifecycleStatus",
    "HarnessProvider",
    "HarnessProvisioningRequest",
    "HarnessProvisioningResult",
    "HarnessTarget",
    "OpenAIHarnessClient",
    "all_providers",
    "get_private_execution_credentials",
    "get_provider",
    "register_provider",
    "resolve_agent_harness",
    "projected_skill_agent_ids",
    "request_skill_sync",
]
