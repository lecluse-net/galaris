"""Operator-owned Compose defaults shared by every managed harness provider."""

from __future__ import annotations

import copy
from typing import Any, cast

import yaml

from core.params import Params, params_service
from core.util import deep_merge


def merge_compose_defaults(
    compose: dict[str, Any], defaults: str | None, *, service_name: str,
) -> dict[str, Any]:
    """Map the common `services.agent` override to the provider's main service."""
    if not defaults or not defaults.strip():
        return copy.deepcopy(compose)
    parsed: object = yaml.safe_load(defaults)
    if not isinstance(parsed, dict):
        raise ValueError("Harness Compose defaults must be a YAML mapping.")
    overrides = copy.deepcopy(cast(dict[str, Any], parsed))
    services = overrides.get("services")
    if isinstance(services, dict) and service_name != "agent":
        service_overrides = cast(dict[str, Any], services)
        if "agent" in service_overrides:
            if service_name in service_overrides:
                raise ValueError("Harness Compose defaults contain conflicting service overrides.")
            service_overrides[service_name] = service_overrides.pop("agent")
    return deep_merge(compose, overrides)


async def configured_compose(content: str, *, service_name: str) -> str:
    parsed: object = yaml.safe_load(content)
    if not isinstance(parsed, dict):
        raise ValueError("Harness Compose template must be a YAML mapping.")
    defaults = await params_service.get(Params.HARNESS_DEFAULT_COMPOSE)
    result = merge_compose_defaults(cast(dict[str, Any], parsed), defaults, service_name=service_name)
    return str(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
