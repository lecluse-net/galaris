"""Agent policy inventory for existing connections, including inactive and blocked access."""

import asyncio
from typing import Literal

from pydantic import BaseModel, Field

from app.agent import effective_tool_profile, get_agent_record, validate_agent_driver
from app.connection import facade as connections

from . import tool_service
from .contracts import MANAGEMENT_SCOPE_PARAM
from .schemas import ConnectionParamOption
from .mcp_loader import list_external_mcp_capabilities, mcp_tools_by_tool_code, native_tool_codes_for_tool

State = Literal["enabled", "disabled", "ask"]
Override = Literal["enabled", "disabled", "ask", "default"]
Kind = Literal["tool", "resource", "prompt"]


class ManagementScopePermission(BaseModel):
    value: str
    configured: str | None
    default: str
    options: list[ConnectionParamOption]
    description: str


class ConnectionPermission(BaseModel):
    tool_id: int
    tool_code: str
    tool_label: str
    description: str
    connection_id: int | None
    active: bool
    can_disable: bool
    parameters: dict[str, str | None] = Field(default_factory=dict)
    parameter_sources: dict[str, str] = Field(default_factory=dict[str, str])
    management_scope: ManagementScopePermission | None = None


class CapabilityPermission(BaseModel):
    id: str
    tool_id: int
    tool_label: str
    connection_id: int | None
    name: str
    description: str
    capability_kind: Kind
    connection_state: Override
    global_state: Override
    default_state: State
    effective_state: State
    policy_state: State
    policy_source: str
    available: bool
    runtime_supported: bool


class AgentPermissionCatalog(BaseModel):
    connections: list[ConnectionPermission] = Field(default_factory=list[ConnectionPermission])
    capabilities: list[CapabilityPermission] = Field(default_factory=list[CapabilityPermission])
    unavailable_catalogs: list[str] = Field(default_factory=list[str])


async def agent_permission_catalog(agent_id: int) -> AgentPermissionCatalog:
    agent = await get_agent_record(agent_id)
    if agent is None:
        raise LookupError("Agent not found")
    runtime = validate_agent_driver(agent.agent_driver, require_available=False)
    profile = await effective_tool_profile(agent_id, runtime)
    configured = {row.tool_id: row for row in await connections.get_connections_by_agent(agent_id, active_only=False)}
    native = mcp_tools_by_tool_code()
    result = AgentPermissionCatalog()
    for record in await tool_service.get_all_tool_records():
        tool = tool_service._to_internal(record)  # pyright: ignore[reportPrivateUsage]
        connection = configured.get(record.id)
        if connection is None:
            continue
        active = bool(connection and connection.active)
        safe_parameters: dict[str, str | None] = {}
        parameter_sources: dict[str, str] = {}
        management_scope: ManagementScopePermission | None = None
        if connection:
            _, parameters = await connections.get_params_as_dict(connection.id, decrypt_passwords=False)
            _, local_parameters, _ = await connections.get_params_for_api(connection.id)
            global_parameters = tool_service.public_global_params(record)
            scope_definition = tool.connection.params.get(MANAGEMENT_SCOPE_PARAM)
            if scope_definition and scope_definition.options and scope_definition.type != "password":
                scope_value = await connections.get_management_scope(agent_id, connection_id=connection.id, default=scope_definition.default)
                local_scope = local_parameters.get(MANAGEMENT_SCOPE_PARAM)
                management_scope = ManagementScopePermission(value=scope_value, configured=local_scope,
                    default=scope_definition.default, options=scope_definition.options, description=scope_definition.description)
                safe_parameters[MANAGEMENT_SCOPE_PARAM] = scope_value
                parameter_sources[MANAGEMENT_SCOPE_PARAM] = "connection" if local_scope is not None else "software"
            for key in ("public_access_mode", "allow_local_network", "network_filter_mode", "network_filter", "permission_methods"):
                definition = tool.connection.params.get(key)
                if key in parameters and (definition is None or definition.type != "password"):
                    safe_parameters[key] = str(parameters[key]) if parameters[key] is not None else None
                    global_parameter = global_parameters.get(key)
                    parameter_sources[key] = ("tool" if global_parameter and global_parameter.forced else
                        "connection" if key in local_parameters else
                        "tool" if global_parameter and global_parameter.configured else "software")
        result.connections.append(ConnectionPermission(tool_id=record.id, tool_code=tool.code,
            tool_label=tool.label, description=tool.description or "", connection_id=connection.id if connection else None,
            active=active, can_disable=tool.can_disable, parameters=safe_parameters, parameter_sources=parameter_sources,
            management_scope=management_scope))
        local = await connections.list_function_states(connection.id) if connection else []
        global_rows = await connections.list_tool_function_states(record.id)
        definitions = {definition.name: definition for code in native_tool_codes_for_tool(tool)
            for definition in native.get(code, [])}
        descriptions: dict[tuple[Kind, str], tuple[str, bool]] = {
            ("tool", name): (definition.description, True) for name, definition in definitions.items()}
        if tool.mcp and active and connection:
            try:
                _, params = await connections.get_params_as_dict(connection.id, decrypt_passwords=True)
                exposed = await asyncio.wait_for(list_external_mcp_capabilities(tool, params, include_resources=False), timeout=10)
                for name, description, kind in exposed:
                    descriptions[(kind, name)] = (description, True)
            except Exception:
                # An offline connector never erases its stored policies or becomes an empty success.
                result.unavailable_catalogs.append(tool.label)
        elif tool.mcp:
            result.unavailable_catalogs.append(tool.label)
        for rule in [*global_rows, *local]:
            if rule.capability_kind == "resource":
                continue
            kind: Kind = "resource" if rule.capability_kind == "resource" else "prompt" if rule.capability_kind == "prompt" else "tool"
            descriptions.setdefault((kind, rule.function_name), ("", False))
        for (kind, name), (description, available) in sorted(descriptions.items()):
            definition = definitions.get(name) if kind == "tool" else None
            default = definition.approval if definition else "enabled"
            policy = connections.project_function_policy(name,
                {row.function_name: connections.stored_function_state(row) for row in local if row.capability_kind == kind},
                {row.function_name: connections.stored_function_state(row) for row in global_rows if row.capability_kind == kind},
                default=default, capability_kind=kind, native=definition is not None)
            supported = definition is None or profile.supports(definition.required_capabilities)
            result.capabilities.append(CapabilityPermission(id=f"{record.id}:{kind}:{name}", tool_id=record.id,
                tool_label=tool.label, connection_id=connection.id if connection else None,
                name=name, description=description, capability_kind=kind, available=available,
                runtime_supported=supported, connection_state=policy["connection_state"], global_state=policy["global_state"],
                default_state=policy["default_state"], policy_state=policy["effective_state"],
                effective_state=policy["effective_state"] if active and supported else "disabled",
                policy_source=policy["policy_source"]))
    return result
