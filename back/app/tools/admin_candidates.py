"""Encrypted, bounded human-prepared MCP candidates; never a durable vault."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass

from core.util import get_encryption_service

from .admin_contracts import AdministrationError, CandidateRequest, AdminToolCreate
from .admin_network import origin


@dataclass(frozen=True)
class _Candidate:
    agent_id: int
    expires: float
    encrypted: str


_candidates: dict[str, _Candidate] = {}


def prepare_candidate(data: CandidateRequest) -> dict[str, object]:
    config = data.definition.mcp_config
    if config is None or config.type not in {"http", "sse"}:
        raise AdministrationError("configuration_invalid", "Only HTTP/SSE candidates are supported.")
    origin(config.url or "")
    if config.auth.url_param:
        raise AdministrationError("configuration_invalid", "Credentials in MCP URLs are prohibited.")
    validate_credential_schema(data.definition)
    definitions = data.definition.connection_schema.params if data.definition.connection_schema else {}
    if len(data.params) > 100 or any(name not in definitions for name in data.params):
        raise AdministrationError("configuration_invalid", "Unknown or excessive candidate parameters.")
    from app.connection.facade import validate_param_value

    for name, value in data.params.items():
        if value:
            validate_param_value(definitions[name].type, value)
    now = time.monotonic()
    for reference, item in list(_candidates.items()):
        if item.expires <= now:
            del _candidates[reference]
    if len(_candidates) >= 32:
        raise AdministrationError("conflict", "The candidate capacity is full; retry after expiry.")
    if len(data.model_dump_json().encode()) > 131072:
        raise AdministrationError("configuration_invalid", "Candidate exceeds the byte limit.")
    reference = secrets.token_urlsafe(32)
    _candidates[reference] = _Candidate(
        data.agent_id, now + 900,
        get_encryption_service().encrypt(data.model_dump_json()),
    )
    return {"reference": reference, "agent_id": data.agent_id, "expires_in_seconds": 900, "code": data.definition.code}


def validate_credential_schema(data: AdminToolCreate) -> None:
    config = data.mcp_config
    if config is None:
        return
    definitions = data.connection_schema.params if data.connection_schema else {}
    names = [config.auth.password_param] if config.auth.type == "basic" else [config.auth.param] if config.auth.param else []
    if any(name not in definitions or definitions[name].type != "password" for name in names):
        raise AdministrationError("configuration_invalid", "Authentication parameters must be declared secret.")
    if any(param.type == "password" and f"${{connection:{name}}}" in (config.url or "")
           for name, param in definitions.items()):
        raise AdministrationError("configuration_invalid", "Secret references cannot appear in a URL.")


def resolve_candidate(reference: str, agent_id: int) -> CandidateRequest:
    item = _candidates.get(reference)
    if item is None or item.agent_id != agent_id or item.expires <= time.monotonic():
        raise AdministrationError("not_found", "Candidate reference is absent, expired or belongs to another agent.")
    return CandidateRequest.model_validate(json.loads(get_encryption_service().decrypt(item.encrypted)))
