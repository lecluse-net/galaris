"""Delegated administration orchestration, shared with future AgentAdmin."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any, cast

from sqlalchemy import JSON, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import load_only

from core import settings
from core.database import get_db, release_db_transaction
from core.util import SECRET_MASK

from . import service
from .admin_candidates import resolve_candidate, validate_credential_schema
from .admin_contracts import (
    AdminServiceCreate, AdminServiceUpdate, AdministrationContext, AdministrationError,
    CandidatePreview, FunctionState, PageRequest, ParamWrite,
)
from .admin_network import diagnostic_client, origin, resolve_destination
from .administration_lock import lock_services
from .mandatory_services import INTEGRATED_SERVICE_CODES, INTEGRATED_SERVICE_SPECS
from .mcp_diagnostics import diagnose_mcp_connection, function_detail
from .mcp_loader import McpToolContext, build_galaris_fastmcp, list_enabled_native_mcp_definitions, native_service_codes_for_service
from .models import Service
from .projections import to_public
from .schemas import McpConfig, ServiceGlobalParamsUpdate, ServiceGlobalParamUpdate, ServiceMcpTestRequest
from .secrets import is_connection_reference, runtime_mcp_config


async def invoke(ctx: McpToolContext, name: str, operation: Callable[..., Awaitable[dict[str, Any]]], **arguments: Any) -> str:
    actor = AdministrationContext(agent_id=ctx.agent_id, function_name=name)
    try:
        await actor.require()
        result = await operation(actor, **arguments)
        return json.dumps({"success": True, **result}, ensure_ascii=False, default=str)
    except AdministrationError as exc:
        await get_db().rollback()
        return json.dumps({"success": False, "error": {"kind": exc.kind, "message": str(exc), "details": exc.details}})
    except IntegrityError:
        await get_db().rollback()
        return json.dumps({"success": False, "error": {"kind": "conflict", "message": "A concurrent change conflicts with this operation; reconcile by code or agent/Service pair."}})
    except ValueError:
        await get_db().rollback()
        return json.dumps({"success": False, "error": {"kind": "configuration_invalid", "message": "Invalid administration configuration."}})


async def record(service_id: int) -> Service:
    tool = await service.get_service_record_by_id(service_id)
    if tool is None:
        raise AdministrationError("not_found", "Service not found.")
    return tool


async def fingerprint(tool: Service, *, connection_id: int | None = None) -> str:
    from app.connection.facade import administration

    state = await administration.snapshot(tool.id, connection_id=connection_id)
    state["tool"] = {column.name: getattr(tool, column.name) for column in Service.__table__.columns
                     if column.name not in {"embedding", "search_vector", "description_embedding"}}
    ids = [item["id"] for item in state["connections"]]
    state["references"] = await administration.references(ids, service_id=tool.id)
    payload = json.dumps(state, sort_keys=True, default=str, ensure_ascii=False).encode()
    return hmac.new(settings.ENCRYPTION_MASTER_KEY.encode(), payload, hashlib.sha256).hexdigest()


async def get(actor: AdministrationContext, service_id: int | None = None, code: str = "") -> dict[str, Any]:
    await actor.require()
    tool = await record(service_id) if service_id is not None else await service.get_service_record(code)
    if tool is None:
        raise AdministrationError("not_found", "Service not found.")
    data = to_public(tool).model_dump(mode="json")
    if tool.mcp_config and tool.mcp_config.get("type") == "stdio":
        data["mcp_config"] = {"type": "stdio", "command_configured": bool(tool.mcp_config.get("command"))}
        for parameter in data["connection_schema"]["params"].values():
            parameter["default"] = None
        for parameter in data["global_params"].values():
            parameter["value"] = None
    # Legacy URL authentication remains recognizable without disclosing its query.
    for name in ("mcp_config", "rest_config", "file_share_config", "listener_config"):
        config = data.get(name)
        if isinstance(config, dict):
            for field in ("url", "base_url"):
                value = cast(dict[str, Any], config).get(field)
                if isinstance(value, str):
                    from urllib.parse import urlsplit, urlunsplit

                    url = urlsplit(value)
                    config[field] = urlunsplit((url.scheme, url.netloc.split("@")[-1], url.path, "", ""))
    allowed: list[str] = []
    for action, definition in (("settings", False), ("definition", True)):
        try:
            actor.require_global()
            actor.require_target(tool.code, can_disable=tool.can_disable, definition=definition,
                                 executable=(tool.mcp_config or {}).get("type") == "stdio")
            allowed.append(action)
        except AdministrationError:
            pass
    return {"tool": data, "version": await fingerprint(tool), "allowed_actions": allowed}


async def list_services(actor: AdministrationContext, search: str = "", kind: str = "", capability: str = "",
                     offset: int = 0, limit: int = 50) -> dict[str, Any]:
    await actor.require()
    PageRequest(offset=offset, limit=limit)
    query = select(Service)
    if search:
        query = query.where(Service.code.ilike(f"%{search}%") | Service.label.ilike(f"%{search}%"))
    if kind == "integrated":
        query = query.where(Service.code.in_(INTEGRATED_SERVICE_CODES))
    elif kind == "custom":
        query = query.where(Service.code.not_in(INTEGRATED_SERVICE_CODES))
    elif kind == "system":
        query = query.where(Service.can_disable.is_(False))
    elif kind:
        raise AdministrationError("configuration_invalid", "Unknown Service kind filter.")
    if capability:
        columns = {"mcp": Service.mcp_config, "api": Service.rest_config, "file_share": Service.file_share_config, "messenger": Service.messenger_config,
                   "listener": Service.listener_config, "mail": Service.mail_config, "calendar": Service.calendar_config, "task": Service.task_config}
        if capability not in columns:
            raise AdministrationError("configuration_invalid", "Unknown capability filter.")
        configured = columns[capability].is_not(None) & (columns[capability] != JSON.NULL) & (columns[capability] != {})
        if capability in {"mail", "calendar"}:
            configured = columns[capability].is_not(None) & (columns[capability] != JSON.NULL)
        if capability == "mcp":
            configured = configured | Service.code.in_([spec.code for spec in INTEGRATED_SERVICE_SPECS if spec.mcp_tools])
        query = query.where(configured)
    total = await get_db().scalar(select(func.count()).select_from(query.subquery()))
    tools = (await get_db().scalars(query.options(load_only(
        Service.id, Service.code, Service.label, Service.can_disable, raiseload=True,
    )).order_by(Service.code).offset(offset).limit(limit))).all()
    return {"total": total, "offset": offset, "limit": limit,
            "items": [{"id": tool.id, "code": tool.code, "label": tool.label, "integrated": tool.code in INTEGRATED_SERVICE_CODES,
                       "system": not tool.can_disable} for tool in tools]}


async def impact(actor: AdministrationContext, service_id: int, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    await actor.require()
    actor.require_global()
    PageRequest(offset=offset, limit=limit)
    from app.connection.facade import administration

    tool = await record(service_id)
    page = await administration.list_connections(service_id=service_id, offset=offset, limit=limit)
    snapshot = await administration.snapshot(service_id)
    ids = [row["id"] for row in snapshot["connections"]]
    agents = sorted({row["agent_id"] for row in snapshot["connections"]})
    references = await administration.references(ids, service_id=service_id)
    return {"service_id": service_id, "version": await fingerprint(tool), "connections": page,
            "agents": {"total": len(agents), "offset": offset, "limit": limit, "items": agents[offset:offset+limit]},
            "references": {"total": len(references), "offset": offset, "limit": limit, "items": references[offset:offset+limit]},
            "deletion_blocked": bool(ids or references)}


async def _lock_mutation(actor: AdministrationContext, service_id: int, expected_version: str,
                         *, connection_id: int | None = None, definition: bool = False,
                         global_mutation: bool = True) -> Service:
    from app.connection.facade import administration

    caller = await service.get_service_record("service_admin") if actor.agent_id is not None else None
    await lock_services([service_id, *([caller.id] if caller else [])])
    await actor.require()
    tool = await record(service_id)
    if connection_id is None and global_mutation:
        actor.require_global()
    actor.require_target(tool.code, can_disable=tool.can_disable, definition=definition,
                         executable=(tool.mcp_config or {}).get("type") == "stdio")
    if connection_id is not None:
        await administration.lock_connection(connection_id)
        connection = await administration.require_target(actor, connection_id)
        if connection.service_id != service_id:
            raise AdministrationError("conflict", "Connection identity changed; read it again.")
    if not expected_version or not hmac.compare_digest(expected_version, await fingerprint(tool, connection_id=connection_id)):
        raise AdministrationError("conflict", "Configuration changed; read the current state before retrying.")
    return tool


def _safe_mcp(config: McpConfig | None, *, literals: bool = False) -> None:
    if config is None:
        return
    if config.type not in {"http", "sse"} or config.command or config.args or config.env:
        raise AdministrationError("configuration_invalid", "ServiceAdmin V1 supports HTTP/SSE only.")
    origin(config.url or "")
    if config.auth.url_param:
        raise AdministrationError("configuration_invalid", "Credentials in URLs are prohibited.")
    if not literals and (config.auth.token_static not in (None, "", SECRET_MASK) or any(
        value and value != SECRET_MASK and not is_connection_reference(value) for value in config.headers.values()
    )):
        raise AdministrationError("configuration_invalid", "Use a human-prepared candidate for secret literals.")


async def refresh_batch(agent_ids: list[int], *, actor: AdministrationContext | None = None,
                        timeout_seconds: float = 20.0) -> dict[str, Any]:
    from .catalog_refresh_service import refresh_agents_tool_catalogs

    selected, remaining = agent_ids[:10], agent_ids[10:]
    if not selected:
        return {"complete": True, "agents_refreshed": 0, "remaining_agent_ids": []}
    try:
        async with asyncio.timeout(timeout_seconds):
            if actor is not None:
                await actor.require()
                for identifier in selected:
                    actor.require_agent(identifier)
            await release_db_transaction()
            result = await refresh_agents_tool_catalogs(selected, allow_stdio=False)
            if actor is not None:
                caller = await service.get_service_record("service_admin")
                if caller is not None:
                    await lock_services([caller.id])
                await actor.require()
            await get_db().commit()
        return {**asdict(result), "complete": result.complete and not remaining, "remaining_agent_ids": remaining}
    except asyncio.CancelledError:
        await get_db().rollback()
        raise
    except AdministrationError:
        await get_db().rollback()
        return {"complete": False, "error": "access_denied", "remaining_agent_ids": agent_ids}
    except TimeoutError:
        await get_db().rollback()
        return {"complete": False, "error": "catalog_refresh_timeout", "remaining_agent_ids": agent_ids}
    except Exception:
        await get_db().rollback()
        return {"complete": False, "error": "catalog_refresh_failed", "remaining_agent_ids": agent_ids}


async def refresh_catalogs(actor: AdministrationContext, agent_ids: list[int], *,
                           timeout_seconds: float = 20.0) -> dict[str, Any]:
    """Reconcile directly, committing each agent and returning unfinished work for retry."""
    remaining = sorted(set(agent_ids))
    failed: list[int] = []
    totals = {name: 0 for name in (
        "agents_scanned", "agents_refreshed", "agent_failures", "source_failures",
        "tools_discovered", "documents_indexed", "embeddings_refreshed", "documents_pruned",
    )}
    semantic_available = True
    degradation_reason: str | None = None
    error: str | None = None
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while remaining:
        budget = deadline - asyncio.get_running_loop().time()
        if budget <= 0:
            error = "catalog_refresh_timeout"
            break
        identifier = remaining[0]
        result = await refresh_batch([identifier], actor=actor, timeout_seconds=budget)
        if result.get("error"):
            error = str(result["error"])
            break
        remaining.pop(0)
        for name in totals:
            totals[name] += int(result.get(name, 0))
        semantic_available = semantic_available and bool(result.get("semantic_available", False))
        degradation_reason = result.get("degradation_reason") or degradation_reason
        if not result["complete"]:
            failed.append(identifier)
    return {**totals, "complete": not remaining and not failed,
            "failed_agent_ids": failed, "remaining_agent_ids": remaining,
            "semantic_available": semantic_available, "degradation_reason": degradation_reason,
            **({"error": error} if error else {})}


async def _saved(actor: AdministrationContext, service_id: int, *, connection_id: int | None = None,
                 deleted: bool = False, agent_ids: list[int] | None = None) -> dict[str, Any]:
    from app.connection.facade import get_agent_ids_by_tool

    await actor.require()
    await get_db().commit()
    try:
        data = {"deleted": True, "service_id": service_id} if deleted else (
            await connection_get(actor, connection_id=connection_id) if connection_id is not None else await get(actor, service_id)
        )
        ids = agent_ids if agent_ids is not None else await get_agent_ids_by_tool(service_id)
        await release_db_transaction()
        return {**data, "persisted": True, "refresh": await refresh_catalogs(actor, ids)}
    except Exception:
        await get_db().rollback()
        return {"service_id": service_id, "connection_id": connection_id, "deleted": deleted, "persisted": True,
                "refresh": {"complete": False, "error": "post_commit_reconciliation_failed"}}


def _secret_definition(data: AdminServiceCreate | AdminServiceUpdate) -> None:
    if data.connection_schema:
        for name, param in data.connection_schema.params.items():
            if len(name) > 100 or not name or (param.type == "password" and param.default):
                raise AdministrationError("configuration_invalid", "Invalid parameter name or secret default.")
    if data.listener_config and data.listener_config.token not in (None, "", SECRET_MASK):
        raise AdministrationError("configuration_invalid", "Listener secrets must be entered by a human.")
    if data.messenger_config:
        secret_fields = service.messenger_secret_fields(data.messenger_config.service)
        if any(data.messenger_config.settings.get(name) not in (None, "", SECRET_MASK) for name in secret_fields):
            raise AdministrationError("configuration_invalid", "Messenger secrets must be entered by a human.")


async def create(actor: AdministrationContext, definition: dict[str, Any] | None = None,
                 candidate_reference: str = "") -> dict[str, Any]:
    await actor.require()
    actor.require_global()
    candidate = resolve_candidate(candidate_reference, actor.agent_id or 0) if candidate_reference else None
    if candidate is not None and definition is not None:
        raise AdministrationError("configuration_invalid", "Choose a definition or a prepared candidate.")
    data = candidate.definition if candidate is not None else AdminServiceCreate.model_validate(definition)
    validate_credential_schema(data)
    actor.require_target(data.code, can_disable=True, definition=True)
    _safe_mcp(data.mcp_config, literals=candidate is not None)
    if candidate is None:
        _secret_definition(data)
        if data.mcp_config:
            await resolve_destination(data.mcp_config.url or "", allow_private=False)
    caller = await service.get_service_record("service_admin")
    if caller is not None:
        await lock_services([caller.id])
    await actor.require()
    if await service.has_service(data.code):
        raise AdministrationError("conflict", "Service code already exists; reconcile by code.")
    tool = await service.create_service(data, commit=False)
    if candidate is not None and candidate.params:
        await service.update_global_params(tool.id, ServiceGlobalParamsUpdate(params={
            name: ServiceGlobalParamUpdate(value=value) for name, value in candidate.params.items()
        }), commit=False)
    return await _saved(actor, tool.id)


async def update(actor: AdministrationContext, service_id: int, changes: dict[str, Any], expected_version: str) -> dict[str, Any]:
    data = AdminServiceUpdate.model_validate(changes)
    _secret_definition(data)
    _safe_mcp(data.mcp_config)
    tool = await _lock_mutation(actor, service_id, expected_version, definition=True)
    if "connection_schema" in data.model_fields_set:
        old = cast(dict[str, dict[str, Any]], (tool.connection_schema or {}).get("params") or {})
        new = data.connection_schema.params if data.connection_schema else {}
        if any(definition.get("type") == "password" and (name not in new or new[name].type != "password")
               for name, definition in old.items()):
            raise AdministrationError("configuration_invalid", "A secret parameter cannot be removed or made public through ServiceAdmin.")
    for field, keys in (("mcp_config", ("url",)), ("rest_config", ("base_url", "auth", "header_params")), ("file_share_config", ("service", "base_url", "param_map")),
                        ("listener_config", ("url", "connection_key")), ("messenger_config", ("service", "settings", "param_map"))):
        config = getattr(data, field)
        if field not in data.model_fields_set or config is None:
            continue
        previous = cast(dict[str, Any], getattr(tool, field) or {})
        current = config.model_dump()
        if any(previous.get(key) != current.get(key) for key in keys):
            raise AdministrationError("configuration_invalid", "A new destination needs a separately prepared Service; existing credentials cannot be transferred.")
    await service.update_service(service_id, data, commit=False)
    return await _saved(actor, service_id)


async def delete_service(actor: AdministrationContext, service_id: int, expected_version: str) -> dict[str, Any]:
    from app.connection.facade import get_agent_ids_by_tool, administration

    await _lock_mutation(actor, service_id, expected_version, definition=True)
    if await get_agent_ids_by_tool(service_id) or await administration.references([], service_id=service_id):
        raise AdministrationError("dependencies_blocking", "Remove Service dependencies explicitly before deletion.", details=await impact(actor, service_id))
    await service.delete_service(service_id, commit=False)
    return await _saved(actor, service_id, deleted=True, agent_ids=[])


async def _param_writes(actor: AdministrationContext, tool: Service, params: dict[str, Any]) -> dict[str, ParamWrite]:
    definitions = cast(dict[str, dict[str, Any]], (tool.connection_schema or {}).get("params") or {})
    writes: dict[str, ParamWrite] = {}
    if len(params) > 100:
        raise AdministrationError("configuration_invalid", "Too many parameters.")
    for name, raw in params.items():
        write = ParamWrite.model_validate(raw)
        definition = definitions.get(name)
        if definition is None:
            raise AdministrationError("configuration_invalid", "Unknown parameter.")
        if definition.get("type") == "password":
            if write.value is not None:
                raise AdministrationError("configuration_invalid", "Secret values must use a human-prepared reference.")
            if write.secret_reference:
                candidate = resolve_candidate(write.secret_reference, actor.agent_id or 0)
                config = candidate.definition.mcp_config
                if candidate.definition.code != tool.code or config is None or config.url != (tool.mcp_config or {}).get("url"):
                    raise AdministrationError("access_denied", "Secret reference is bound to a different Service or endpoint.")
                write.value = candidate.params.get(name)
                if write.value is None:
                    raise AdministrationError("configuration_invalid", "The candidate does not contain that secret parameter.")
        elif write.secret_reference:
            raise AdministrationError("configuration_invalid", "Secret references require secret parameters.")
        writes[name] = write
    return writes


async def global_params_set(actor: AdministrationContext, service_id: int, params: dict[str, Any], expected_version: str) -> dict[str, Any]:
    tool = await _lock_mutation(actor, service_id, expected_version)
    writes = await _param_writes(actor, tool, params)
    # URL templates can redirect an inherited secret; keep their destination parameters human-only.
    _protect_destination_params(tool, writes)
    await service.update_global_params(service_id, ServiceGlobalParamsUpdate(params={
        name: ServiceGlobalParamUpdate(value=write.value, clear=write.clear,
            forced=write.forced if "forced" in write.model_fields_set else bool((tool.global_params or {}).get(name, {}).get("forced")))
        for name, write in writes.items()
    }), commit=False)
    return await _saved(actor, service_id)


def _protect_destination_params(tool: Service, params: dict[str, Any]) -> None:
    configs = (tool.mcp_config, tool.rest_config, tool.file_share_config, tool.listener_config)
    for config in configs:
        if not config:
            continue
        for key in ("url", "base_url"):
            value = str(config.get(key) or "")
            if any(f"${{connection:{name}}}" in value for name in params):
                raise AdministrationError("access_denied", "Destination parameters require human administration.")


async def mcp_test(actor: AdministrationContext, service_id: int | None = None, connection_id: int | None = None,
                   candidate: dict[str, Any] | None = None, candidate_reference: str = "",
                   offset: int = 0, limit: int = 50, include_details: bool = False) -> dict[str, Any]:
    await actor.require()
    if service_id is not None and connection_id is None:
        actor.require_global()
    PageRequest(offset=offset, limit=limit)
    from app.connection.facade import get_connection, get_params_as_dict, mcp_oauth_auth

    choices = sum((service_id is not None, connection_id is not None, candidate is not None, bool(candidate_reference)))
    if choices != 1:
        raise AdministrationError("configuration_invalid", "Choose exactly one diagnostic source.")
    allow_private = service_id is not None or connection_id is not None or bool(candidate_reference)
    existing = None
    mcp_auth = None
    if candidate_reference:
        prepared = resolve_candidate(candidate_reference, actor.agent_id or 0)
        config = prepared.definition.mcp_config
        assert config is not None
        request = ServiceMcpTestRequest(code=prepared.definition.code, mcp_config=config, params=prepared.params)
    elif candidate is not None:
        request = CandidatePreview.model_validate(candidate)
        _safe_mcp(request.mcp_config)
        if request.params or request.service_id is not None:
            raise AdministrationError("configuration_invalid", "Temporary credentials require a human-prepared candidate.")
    else:
        if connection_id is not None:
            connection = await get_connection(connection_id)
            if connection is None:
                raise AdministrationError("not_found", "Connection not found.")
            actor.require_agent(connection.agent_id)
            service_id = connection.service_id
            _, params = await get_params_as_dict(connection_id)
        else:
            assert service_id is not None
            params, _ = await service.get_runtime_global_params(service_id)
        assert service_id is not None
        tool = await record(service_id)
        if not tool.mcp_config:
            raise AdministrationError("configuration_invalid", "Service has no external MCP configuration.")
        existing = tool.mcp_config
        request = ServiceMcpTestRequest(code=tool.code, mcp_config=McpConfig(**runtime_mcp_config(existing)), params=params)
        if connection_id is not None:
            mcp_auth = mcp_oauth_auth(params, request.mcp_config.url or "")
    _safe_mcp(request.mcp_config, literals=True)
    secret_values = [str(value) for value in request.params.values() if value]
    if any(f"${{connection:{name}}}" in (request.mcp_config.url or "") for name in request.params):
        raise AdministrationError("configuration_invalid", "Resolved parameter URLs require human-only diagnostics.")
    secret_values.extend(value for value in request.mcp_config.headers.values() if value and not is_connection_reference(value))
    if request.mcp_config.auth.token_static:
        secret_values.append(request.mcp_config.auth.token_static)
    await release_db_transaction()
    try:
        client = await diagnostic_client(request.mcp_config.url or "", allow_private=allow_private)
        try:
            result = await diagnose_mcp_connection(request, existing_config=existing, http_client=client, mcp_auth=mcp_auth)
        finally:
            await client.aclose()
    except Exception as exc:
        from .mcp_diagnostics import classify_mcp_exception

        return {"diagnostic": {"success": False, "failure_kind": classify_mcp_exception(exc), "message": "MCP diagnostic failed.", "tools": []}}
    payload = result.model_dump(mode="json")
    payload["total"] = len(payload["tools"])
    payload["offset"] = offset
    payload["limit"] = limit
    payload["tools"] = payload["tools"][offset:offset+limit]
    if not include_details:
        payload["tools"] = [{key: value for key, value in item.items() if key not in {"input_schema", "output_schema", "annotations"}}
                            for item in payload["tools"]]
    # Server-provided descriptions and schemas may echo credentials; scrub known literals.
    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for secret in sorted(secret_values, key=len, reverse=True):
                value = value.replace(secret, "[redacted]")
            return value
        if isinstance(value, list):
            return [scrub(item) for item in cast(list[Any], value)]
        if isinstance(value, dict):
            return {scrub(key): scrub(item) for key, item in cast(dict[str, Any], value).items()}
        return value
    await actor.require()
    return {"diagnostic": scrub(payload), "source": {"service_id": service_id, "connection_id": connection_id,
            "candidate": candidate is not None or bool(candidate_reference)}}


async def function_list(actor: AdministrationContext, service_id: int, connection_id: int | None = None,
                        offset: int = 0, limit: int = 50, runtime: str = "internal", conversation_only: bool = False,
                        include_details: bool = False) -> dict[str, Any]:
    await actor.require()
    PageRequest(offset=offset, limit=limit)
    from app.connection import facade as connections
    from app.agent import validate_agent_driver, effective_capabilities

    await record(service_id)
    tool = await service.get_service_by_id(service_id)
    assert tool is not None
    connection = await connections.get_connection(connection_id) if connection_id is not None else None
    if connection_id is not None and (connection is None or connection.service_id != service_id):
        raise AdministrationError("not_found", "Connection does not belong to this Service.")
    if connection is not None:
        actor.require_agent(connection.agent_id)
    else:
        actor.require_global()
    target_agent = connection.agent_id if connection is not None else actor.agent_id
    selected_runtime = validate_agent_driver(runtime, require_available=False)
    server = build_galaris_fastmcp(target_agent or 0, runtime=selected_runtime, enabled_service_codes=set(native_service_codes_for_service(tool)))
    native = await server.list_tools()
    functions = [{**function_detail(item).model_dump(mode="json"), "source": "native"} for item in native]
    complete = True
    diagnostics: Any = None
    if tool.mcp:
        result = await mcp_test(actor, limit=500, include_details=True,
                               connection_id=connection_id, service_id=service_id if connection_id is None else None)
        diagnostics = result["diagnostic"]
        complete = bool(diagnostics["success"] and not diagnostics.get("truncated"))
        functions.extend({**item, "source": "external"} for item in diagnostics["tools"])
    globals_ = {row.function_name: connections.stored_function_state(row) for row in await connections.list_service_function_states(service_id) if (row.capability_kind or "tool") == "tool"}
    locals_ = {row.function_name: connections.stored_function_state(row) for row in await connections.list_function_states(connection_id) if (row.capability_kind or "tool") == "tool"} if connection_id is not None else {}
    visible: set[str] = {definition.name for definition in await list_enabled_native_mcp_definitions(
        target_agent or 0, runtime=selected_runtime, conversation_only=conversation_only,
    )} if connection is not None else set()
    external_executable = "execute" in await effective_capabilities(target_agent or 0, selected_runtime) if connection is not None else False
    for item in functions:
        name = item["name"]
        from .mcp_loader import conversation_tool_names, load_mcp_tools
        is_native = item["source"] == "native"
        definition = next((definition for definition in load_mcp_tools() if definition.name == name and definition.service_code in native_service_codes_for_service(tool)), None) if is_native else None
        policy = connections.project_function_policy(name, locals_, globals_, default=definition.approval if definition else "enabled", native=definition is not None)
        effective = policy["effective"]
        conversation_enabled = (definition is None or definition.conversation_policy != "forbidden") and name in conversation_tool_names(
            tool, source="native" if is_native else "external",
        )
        item.update({**policy, "conversation_enabled": conversation_enabled, "available": bool(connection and connection.active and effective and (
                         (not conversation_only or conversation_enabled) and (name in visible if is_native else external_executable)
                     ))})
        if not include_details:
            for key in ("input_schema", "output_schema", "annotations"):
                item.pop(key, None)
    await actor.require()
    return {"service_id": service_id, "connection_id": connection_id, "runtime": selected_runtime, "conversation_only": conversation_only,
            "complete": complete, "diagnostic": diagnostics and {k: v for k, v in diagnostics.items() if k != "tools"},
            "total": len(functions), "offset": offset, "limit": limit, "items": sorted(functions, key=lambda item: item["name"])[offset:offset+limit]}


async def function_get(actor: AdministrationContext, service_id: int, function_name: str, connection_id: int | None = None) -> dict[str, Any]:
    result = await function_list(actor, service_id, connection_id=connection_id, limit=500, include_details=True)
    item = next((row for row in result["items"] if row["name"] == function_name), None)
    if item is None:
        raise AdministrationError("not_found", "Function not discovered in this source.")
    return {"function": item, "complete": result["complete"], "connection_id": connection_id}


async def function_set(actor: AdministrationContext, service_id: int, function_name: str, state: FunctionState, expected_version: str) -> dict[str, Any]:
    from app.connection.facade import set_service_function_state, administration

    _validate_function(function_name, state)
    await _lock_mutation(actor, service_id, expected_version)
    await set_service_function_state(service_id, function_name, state, commit=False)
    snapshot = await administration.snapshot(service_id)
    overrides = [{"connection_id": conn, "state": mode} for conn, kind, name, mode in snapshot["local_states"] if kind == "tool" and name == function_name]
    return {**await _saved(actor, service_id), "function_name": function_name, "global_state": state,
            "local_overrides": overrides[:500], "local_override_count": len(overrides), "overrides_truncated": len(overrides) > 500}


def _validate_function(name: str, state: FunctionState) -> None:
    if not name or len(name) > 255 or state not in {"default", "enabled", "disabled", "ask"}:
        raise AdministrationError("configuration_invalid", "Invalid function name or state.")


async def connection_list(actor: AdministrationContext, service_id: int | None = None, agent_id: int | None = None,
                          active: bool | None = None, offset: int = 0, limit: int = 50) -> dict[str, Any]:
    from app.connection.facade import administration

    await actor.require()
    PageRequest(offset=offset, limit=limit)
    if agent_id is not None:
        actor.require_agent(agent_id)
    return await administration.list_connections(service_id=service_id, agent_id=agent_id, active=active,
        offset=offset, limit=limit, agent_ids=actor.allowed_agent_ids)


async def connection_get(actor: AdministrationContext, connection_id: int | None = None,
                         service_id: int | None = None, agent_id: int | None = None) -> dict[str, Any]:
    from app.connection.facade import administration, get_connection_by_agent_service

    await actor.require()
    if connection_id is None and service_id is not None and agent_id is not None:
        connection = await get_connection_by_agent_service(service_id, agent_id)
        connection_id = connection.id if connection is not None else None
    if connection_id is None:
        raise AdministrationError("not_found", "Connection not found.")
    data = await administration.projection(connection_id)
    actor.require_agent(data["agent_id"])
    return {"connection": data, "version": await fingerprint(await record(data["service_id"]), connection_id=connection_id),
            "references": await administration.references([connection_id])}


async def connection_create(actor: AdministrationContext, service_id: int, agent_id: int, expected_version: str) -> dict[str, Any]:
    from app.connection.facade import administration

    await _lock_mutation(actor, service_id, expected_version, global_mutation=False)
    actor.require_agent(agent_id)
    connection = await administration.create(actor, service_id, agent_id)
    return await _saved(actor, service_id, connection_id=connection.id, agent_ids=[agent_id])


async def connection_mutate(actor: AdministrationContext, connection_id: int, expected_version: str,
                            action: str, active: bool = False, params: dict[str, Any] | None = None,
                            param_name: str = "", function_name: str = "", state: FunctionState = "default") -> dict[str, Any]:
    from app.connection import facade as connections

    connection = await connections.get_connection(connection_id)
    if connection is None:
        raise AdministrationError("not_found", "Connection not found.")
    service_id, agent_id = connection.service_id, connection.agent_id
    tool = await _lock_mutation(actor, service_id, expected_version, connection_id=connection_id)
    if action == "update":
        await connections.set_connection_active(connection_id, active, commit=False)
    elif action == "delete":
        await connections.delete_connection(connection_id, commit=False)
    elif action == "params":
        writes = await _param_writes(actor, tool, params or {})
        if any("forced" in write.model_fields_set for write in writes.values()):
            raise AdministrationError("configuration_invalid", "Only global parameter writes accept forced.")
        _protect_destination_params(tool, writes)
        values: dict[str, str | None] = {name: write.value for name, write in writes.items() if not write.clear and write.value is not None}
        await connections.set_params_bulk(connection_id, values, commit=False)
        for name, write in writes.items():
            if write.clear:
                await connections.delete_param(connection_id, name, commit=False)
    elif action == "param_delete":
        _protect_destination_params(tool, {param_name: None})
        await connections.delete_param(connection_id, param_name, commit=False)
    elif action == "function":
        _validate_function(function_name, state)
        await connections.set_connection_function_state(connection_id, function_name, state, commit=False)
    else:
        raise AdministrationError("configuration_invalid", "Unknown connection action.")
    resolved = await connections.resolve_function(connection, function_name) if action == "function" else {}
    return {**await _saved(actor, service_id, connection_id=None if action == "delete" else connection_id,
                          deleted=action == "delete", agent_ids=[agent_id]),
            **({"connection_id": connection_id} if action == "delete" else {}), **({"function": resolved} if resolved else {})}


async def connection_function_list(actor: AdministrationContext, connection_id: int, offset: int = 0, limit: int = 50,
                                    runtime: str = "internal", conversation_only: bool = False) -> dict[str, Any]:
    from app.connection.facade import get_connection

    connection = await get_connection(connection_id)
    if connection is None:
        raise AdministrationError("not_found", "Connection not found.")
    return await function_list(actor, connection.service_id, connection_id, offset, limit, runtime, conversation_only)


async def catalog_refresh(actor: AdministrationContext, service_id: int | None = None,
                          connection_ids: list[int] | None = None) -> dict[str, Any]:
    from app.connection.facade import get_agent_ids_by_tool, get_connection

    await actor.require()
    if service_id is None and not connection_ids:
        raise AdministrationError("configuration_invalid", "Choose a Service or explicit connection IDs.")
    if service_id is not None:
        await record(service_id)
        agents = await get_agent_ids_by_tool(service_id)
        if actor.allowed_agent_ids is not None:
            agents = [agent for agent in agents if agent in actor.allowed_agent_ids]
    else:
        agents: list[int] = []
        for connection_id in connection_ids or []:
            connection = await get_connection(connection_id)
            if connection is None:
                raise AdministrationError("not_found", "Connection not found.")
            actor.require_agent(connection.agent_id)
            agents.append(connection.agent_id)
    await release_db_transaction()
    return {"refresh": await refresh_catalogs(actor, agents)}
