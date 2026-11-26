"""Merge retired built-in connections without broadening effective permissions."""

from datetime import datetime, timezone
from typing import Literal

from sqlalchemy import Select, delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import Agent
from app.connection import Connection, ConnectionFunctionState, ConnectionParam, ServiceFunctionState
from core.params import Param, Params

from .authorization_models import ActionAuthorization
from .contracts import CHAT_CHANNEL_PARAM, MANAGEMENT_SCOPE_PARAM, VOICE_AUTO_ANSWER_PARAM
from .legacy_names import BUILTIN_TOOL_RENAMES, MERGED_TASK_TOOLS
from .mandatory_services import ADMIN_TOOLS, CHAT_TOOLS, CONVERSATION_INSPECTION_TOOLS, VOICE_TOOLS, AUDIO_TOOLS, IMAGE_TOOLS, SEARCH_TOOLS
from .models import Service

_CHAT_TOOL_RENAMES = {
    "conversation_choice_resolve": "chat_choice_resolve",
    "conversation_round_get": "chat_round_get",
    "repository_show": "chat_repository_show",
}
_LEGACY_CHAT_NAMES = {current: previous for previous, current in _CHAT_TOOL_RENAMES.items()}
_LEGACY_CHAT_TOOLS = tuple(_LEGACY_CHAT_NAMES.get(name, name) for name in CHAT_TOOLS)
MERGES = {
    "platform_admin": {"galaris": ADMIN_TOOLS, "conversation": tuple(
        _LEGACY_CHAT_NAMES.get(name, name) for name in CONVERSATION_INSPECTION_TOOLS
    )},
    "voice": {"conversation": VOICE_TOOLS},
}
FAMILY_MERGES: dict[str, tuple[str, tuple[str, ...]]] = {
    "audio": ("multimedia", AUDIO_TOOLS), "image": ("multimedia", IMAGE_TOOLS), "search": ("browser", SEARCH_TOOLS),
}
State = Literal["enabled", "ask", "disabled"]


def _state(row: ServiceFunctionState | ConnectionFunctionState) -> State:
    if row.state in {"enabled", "ask", "disabled"}:
        if row.state == "ask":
            return "ask"
        return "enabled" if row.state == "enabled" else "disabled"
    return "enabled" if row.enabled else "disabled"


async def _check_references(session: AsyncSession, service: Service, connection_ids: list[int]) -> None:
    # Some dependent tables cascade when a connection disappears. Refuse to
    # retire a Service with business data instead of silently triggering those cascades.
    consumed = {Connection.__tablename__, ConnectionParam.__tablename__, ConnectionFunctionState.__tablename__,
                ServiceFunctionState.__tablename__, ActionAuthorization.__tablename__}
    for table in Service.metadata.tables.values():
        if table.name in consumed:
            continue
        for reference in table.foreign_keys:
            parent = reference.column.table.name
            if parent == "services":
                match = reference.parent == service.id
            elif parent == "connections" and connection_ids:
                match = reference.parent.in_(connection_ids)
            else:
                continue
            if await session.scalar(select(select(reference.parent).where(match).exists())):
                raise ValueError(f"Cannot merge {service.code}: {table.name} still references the retired Service")


async def merge_builtin_services(session: AsyncSession) -> None:
    services = {item.code: item for item in await session.scalars(
        select(Service).where(Service.code.in_(("galaris", "service", "chat", "conversation", *MERGES))).order_by(Service.id).with_for_update(),
    )}
    if MERGES.keys() & services.keys():
        from .mcp_loader import load_mcp_tools

        definitions = load_mcp_tools()
        approvals: dict[str, Literal["enabled", "ask"]] = {
            _LEGACY_CHAT_NAMES.get(tool.name, tool.name): tool.approval for tool in definitions
        }
        # The retired Voice service required consent to initiate calls.
        approvals["voice_call_start"] = "ask"
        available_defaults = {_LEGACY_CHAT_NAMES.get(tool.name, tool.name) for tool in definitions
                              if tool.default_state != "disabled"}
        for code, mapping in MERGES.items():
            if code in services:
                targets = {name: (services.get("conversation") or services["chat"]) if destination == "conversation" else services[destination]
                           for destination, names in mapping.items() for name in names}
                await _merge_service(session, services[code], targets, approvals, available_defaults, services["galaris"])
    if {"galaris", "service"} <= services.keys():
        await _move_galaris_management_scope(session, services["galaris"].id, services["service"].id)


async def merge_conversation_into_chat(session: AsyncSession) -> None:
    """Retire the conversation catalogue entry and retain native Chat identities."""
    services = {row.code: row for row in await session.scalars(select(Service).where(
        Service.code.in_(("chat", "conversation", *MERGES)),
    ).order_by(Service.id).with_for_update())}
    source = services.get("conversation")
    if source is None:
        return
    if services.keys() & MERGES.keys():
        raise ValueError("Cannot merge Conversation before the Administration and Voice transfers have completed")
    chat = services["chat"]
    _require_plain_service(source)
    connections = list(await session.scalars(select(Connection).where(
        Connection.service_id.in_((chat.id, source.id)),
    ).order_by(Connection.id).with_for_update()))
    if any(row.singleton_key != 0 for row in connections):
        raise ValueError("Cannot merge Conversation: more than one connection slot may apply to an agent")
    targets = {row.agent_id: row for row in connections if row.service_id == chat.id}
    origins = {row.agent_id: row for row in connections if row.service_id == source.id}
    origins_by_id = {row.id: row for row in origins.values()}
    origin_ids = list(origins_by_id)
    previously_disabled = {agent_id for agent_id, row in targets.items() if not row.active} | (origins.keys() - targets.keys())
    await _check_references(session, source, origin_ids)
    live = set(await session.scalars(select(Agent.id).where(Agent.id.in_(targets.keys() | origins.keys()))))
    for agent_id, origin in origins.items():
        if agent_id not in targets:
            target = Connection(service_id=chat.id, agent_id=agent_id, active=origin.active and agent_id in live)
            session.add(target)
            await session.flush()
            targets[agent_id] = target
    target_ids = [row.id for row in targets.values()]
    parameters = {(row.connection_id, row.param_name): row for row in await session.scalars(
        select(ConnectionParam).where(ConnectionParam.connection_id.in_(origin_ids + target_ids)),
    )}
    for (connection_id, name), parameter in parameters.items():
        origin = origins_by_id.get(connection_id)
        if origin is None:
            continue
        if name != VOICE_AUTO_ANSWER_PARAM:
            raise ValueError("Cannot merge Conversation: a connection parameter requires an explicit destination")
        target = targets[origin.agent_id]
        value = parameter.param_value if origin.active or origin.agent_id not in live else "false"
        current = parameters.get((target.id, name))
        if current is None:
            parameter.connection_id = target.id
            parameter.param_value = value
        elif current.param_value != value:
            raise ValueError("Cannot merge Conversation: conflicting automatic voice answer settings")
    for agent_id, target in targets.items():
        if agent_id in previously_disabled and (target.id, CHAT_CHANNEL_PARAM) not in parameters:
            session.add(ConnectionParam(connection_id=target.id, param_name=CHAT_CHANNEL_PARAM, param_value="false"))
        if agent_id in live:
            target.active = True

    from .dbadmin import move_function_policies

    await move_function_policies(session, source.id, chat.id, "Conversation and Chat", _LEGACY_CHAT_TOOLS)
    await rebind_action_history(session, source.id, dict.fromkeys(_LEGACY_CHAT_TOOLS, chat.id),
                                {(chat.id, agent_id): row for agent_id, row in targets.items()}, origin_ids=origin_ids)
    # The old service was mandatory. If an old connection was absent or inactive,
    # keep its functions blocked when attaching them to the active Chat connection.
    blocked_ids = [row.id for agent_id, row in targets.items() if agent_id in live
                   and (agent_id not in origins or not origins[agent_id].active)]
    if blocked_ids:
        await session.execute(delete(ConnectionFunctionState).where(
            ConnectionFunctionState.connection_id.in_(blocked_ids),
            ConnectionFunctionState.capability_kind == "tool",
            ConnectionFunctionState.function_name.in_(_LEGACY_CHAT_TOOLS),
        ))
        session.add_all(ConnectionFunctionState(connection_id=connection_id, function_name=name,
                        enabled=False, state="disabled") for connection_id in blocked_ids for name in _LEGACY_CHAT_TOOLS)
    await session.flush()
    if await session.scalar(select(ServiceFunctionState.id).where(ServiceFunctionState.service_id == source.id).limit(1)):
        raise ValueError("Cannot merge Conversation: an unknown global function policy would be lost")
    if await session.scalar(select(ConnectionFunctionState.id).where(
        ConnectionFunctionState.connection_id.in_(origin_ids),
    ).limit(1)):
        raise ValueError("Cannot merge Conversation: an unknown local function policy would be lost")
    if await session.scalar(select(ActionAuthorization.id).where(
        (ActionAuthorization.service_id == source.id) | ActionAuthorization.connection_id.in_(origin_ids),
    ).limit(1)):
        raise ValueError("Cannot merge Conversation: an unknown action authorization would be lost")
    await session.execute(delete(Connection).where(Connection.id.in_(origin_ids)))
    await session.delete(source)
    await session.flush()


async def rename_chat_tools(session: AsyncSession) -> None:
    """Carry Chat function policies forward after the older Service merges."""
    await _rename_builtin_tools(session, "chat", _CHAT_TOOL_RENAMES)


async def rename_domain_tools(session: AsyncSession) -> None:
    for service_code, names in BUILTIN_TOOL_RENAMES.items():
        await _rename_builtin_tools(session, service_code, names)
    await _merge_task_tool_policies(session)


async def _rename_builtin_tools(session: AsyncSession, service_code: str, renames: dict[str, str]) -> None:
    service_id = await session.scalar(select(Service.id).where(Service.code == service_code).with_for_update())
    if service_id is None:
        return
    connection_ids = select(Connection.id).where(Connection.service_id == service_id)
    names = (*renames, *renames.values())
    for model, owner in ((ServiceFunctionState, ServiceFunctionState.service_id),
                         (ConnectionFunctionState, ConnectionFunctionState.connection_id)):
        scope = owner == service_id if model is ServiceFunctionState else owner.in_(connection_ids)
        rows = (await session.execute(select(owner, model).where(
            scope, model.capability_kind == "tool", model.function_name.in_(names),
        ).order_by(model.id).with_for_update())).all()
        policies = {(owner_id, row.function_name): row for owner_id, row in rows}
        for (owner_id, previous_name), previous in policies.items():
            current_name = renames.get(previous_name)
            if current_name is None:
                continue
            current = policies.get((owner_id, current_name))
            if current is None:
                previous.function_name = current_name
            elif _state(previous) == _state(current):
                await session.delete(previous)
            else:
                raise ValueError(f"Conflicting {model.__tablename__} policies for {previous_name} and {current_name}")

    await _invalidate_renamed_approvals(session, service_id, tuple(renames))
    await session.flush()


async def _invalidate_renamed_approvals(
    session: AsyncSession, service_id: int, old_names: tuple[str, ...],
) -> None:
    # Existing one-action approvals are bound to the original name and fingerprint.
    connection_ids = select(Connection.id).where(Connection.service_id == service_id)
    now = datetime.now(timezone.utc)
    await session.execute(update(ActionAuthorization).where(
        (ActionAuthorization.service_id == service_id) | ActionAuthorization.connection_id.in_(connection_ids),
        ActionAuthorization.capability_kind == "tool",
        ActionAuthorization.capability_name.in_(old_names),
        ActionAuthorization.status.in_(("pending", "approved")),
    ).values(status="invalidated", encrypted_arguments=None, notification_due_at=None,
             wake_due_at=now, finished_at=now))


_STATE_RESTRICTION: dict[State, int] = {"enabled": 0, "ask": 1, "disabled": 2}


async def _merge_task_tool_policies(session: AsyncSession) -> None:
    """Keep the most restrictive former effective policy at each connection."""
    service_id = await session.scalar(select(Service.id).where(Service.code == "task").with_for_update())
    if service_id is None:
        return
    connection_ids = select(Connection.id).where(Connection.service_id == service_id)
    marker = await session.get(Param, Params.TASK_RUN_POLICIES_MERGED, with_for_update=True)
    first_run_merge = marker is None or marker.value != "true"
    await _merge_task_tool_policy(session, service_id, connection_ids, "task_run",
                                  {"task_run": "enabled", "task_submit": "ask"},
                                  include_destination_only=first_run_merge)
    await _merge_task_tool_policy(session, service_id, connection_ids, "task_get",
                                  {"task_get": "enabled", "task_status": "enabled"})
    await _merge_task_tool_policy(session, service_id, connection_ids, "task_resume",
                                  {"task_resume": "enabled", "task_retry": "enabled"})
    await _merge_task_tool_policy(session, service_id, connection_ids, "task_cancel",
                                  {"task_stop": "ask", "task_stop_conversation": "ask"})
    retired = tuple(MERGED_TASK_TOOLS)
    await _invalidate_renamed_approvals(session, service_id, (*retired, "task_run") if first_run_merge else retired)
    if marker is None:
        session.add(Param(name=Params.TASK_RUN_POLICIES_MERGED, value="true"))
    elif first_run_merge:
        marker.value = "true"
    await session.flush()


async def _merge_task_tool_policy(
    session: AsyncSession, service_id: int, connection_ids: Select[tuple[int]], name: str,
    previous_defaults: dict[str, State], *, include_destination_only: bool = False,
) -> None:
    retired = previous_defaults.keys() - {name}
    names = retired | {name}
    global_rows = {row.function_name: row for row in await session.scalars(
        select(ServiceFunctionState).where(ServiceFunctionState.service_id == service_id,
            ServiceFunctionState.capability_kind == "tool", ServiceFunctionState.function_name.in_(names))
        .order_by(ServiceFunctionState.id).with_for_update(),
    )}
    local_rows: dict[int, dict[str, ConnectionFunctionState]] = {}
    for row in await session.scalars(
        select(ConnectionFunctionState).where(ConnectionFunctionState.connection_id.in_(connection_ids),
            ConnectionFunctionState.capability_kind == "tool", ConnectionFunctionState.function_name.in_(names))
        .order_by(ConnectionFunctionState.id).with_for_update(),
    ):
        local_rows.setdefault(row.connection_id, {})[row.function_name] = row

    old_globals = dict(previous_defaults)
    old_globals.update((key, _state(row)) for key, row in global_rows.items())
    global_state = max(old_globals.values(), key=_STATE_RESTRICTION.__getitem__)
    if retired & global_rows.keys() or (include_destination_only and name in global_rows):
        current = global_rows.get(name)
        if current is None:
            session.add(ServiceFunctionState(service_id=service_id, function_name=name, state=global_state,
                                             enabled=global_state == "enabled"))
        else:
            current.state, current.enabled = global_state, global_state == "enabled"
        for key in retired & global_rows.keys():
            await session.delete(global_rows[key])

    for connection_id, rows in local_rows.items():
        if not include_destination_only and not (retired & (global_rows.keys() | rows.keys())):
            continue
        old_effective = dict(old_globals)
        old_effective.update((key, _state(row)) for key, row in rows.items())
        state = max(old_effective.values(), key=_STATE_RESTRICTION.__getitem__)
        current = rows.get(name)
        if current is None:
            session.add(ConnectionFunctionState(connection_id=connection_id, function_name=name,
                                                state=state, enabled=state == "enabled"))
        else:
            current.state, current.enabled = state, state == "enabled"
        for key in retired & rows.keys():
            await session.delete(rows[key])


async def _move_galaris_management_scope(session: AsyncSession, origin: int, destination: int) -> None:
    sources = (await session.execute(select(ConnectionParam, Connection).join(Connection).where(
        Connection.service_id == origin, ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM,
    ).with_for_update())).all()
    if not sources:
        return
    agent_ids = {connection.agent_id for parameter, connection in sources if parameter.param_value}
    live = set(await session.scalars(select(Agent.id).where(Agent.id.in_(agent_ids))))
    targets = {row.agent_id: row for row in await session.scalars(select(Connection).where(
        Connection.service_id == destination, Connection.agent_id.in_(agent_ids), Connection.singleton_key == 0,
    ).with_for_update())}
    target_params = {row.connection_id: row for row in await session.scalars(select(ConnectionParam).where(
        ConnectionParam.connection_id.in_({row.id for row in targets.values()}),
        ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM,
    ).with_for_update())}
    for parameter, connection in sources:
        value = parameter.param_value
        if not value:
            await session.delete(parameter)
            continue
        agent_id = connection.agent_id
        target = targets.get(agent_id)
        if target is None:
            target = Connection(service_id=destination, agent_id=agent_id, active=agent_id in live and connection.active)
            session.add(target)
            await session.flush()
            targets[agent_id] = target
        current = target_params.get(target.id)
        if current is not None and current.param_value and current.param_value != value:
            raise ValueError(f"Conflicting Galaris and Services management scopes for agent {agent_id}")
        if agent_id in live and value != "usage" and connection.active != target.active:
            raise ValueError(f"Conflicting Galaris and Services activation for the management scope of agent {agent_id}")
        if current is None:
            parameter.connection_id = target.id
            target_params[target.id] = parameter
        else:
            current.param_value = value
            await session.delete(parameter)
    await session.flush()


async def merge_media_and_search_services(session: AsyncSession) -> None:
    """Retire independently switchable services while preserving each function's availability."""
    codes = {*FAMILY_MERGES, *(target for target, _ in FAMILY_MERGES.values())}
    services = {row.code: row for row in await session.scalars(
        select(Service).where(Service.code.in_(codes)).order_by(Service.id).with_for_update(),
    )}
    from .mcp_loader import mcp_tools_by_service_code

    for code in ("multimedia", "browser"):
        sources = [(services[old], names) for old, (target, names) in FAMILY_MERGES.items()
                   if target == code and old in services]
        if sources:
            definitions = mcp_tools_by_service_code()[code]
            original_defaults: dict[str, State] = {tool.name: tool.approval for tool in definitions}
            if code == "multimedia":
                # These actions required consent on the retired Audio and Image services.
                original_defaults.update(audio_transcribe="ask", image_read="ask")
            await _merge_service_families(session, services[code], sources, original_defaults,
                {tool.name: tool.default_state for tool in definitions})


async def _merge_service_families(
    session: AsyncSession, destination: Service, sources: list[tuple[Service, tuple[str, ...]]],
    original_defaults: dict[str, State], defaults: dict[str, State],
) -> None:
    service_ids = {destination.id, *(source.id for source, _ in sources)}
    connections = list(await session.scalars(select(Connection).where(
        Connection.service_id.in_(service_ids),
    ).order_by(Connection.id).with_for_update()))
    by_service_agent = {(row.service_id, row.agent_id): row for row in connections}
    agent_ids = {row.agent_id for row in connections}
    live_agents = set(await session.scalars(select(Agent.id).where(Agent.id.in_(agent_ids))))
    local = {(row.connection_id, row.function_name, row.capability_kind): row for row in await session.scalars(
        select(ConnectionFunctionState).where(ConnectionFunctionState.connection_id.in_({row.id for row in connections})),
    )}
    global_rules = {(row.service_id, row.function_name, row.capability_kind): row for row in await session.scalars(
        select(ServiceFunctionState).where(ServiceFunctionState.service_id.in_(service_ids)),
    )}
    old_globals: dict[tuple[int, str, str], State] = {key: _state(row) for key, row in global_rules.items()}
    destination_globals: dict[str, State] = {name: state for (service_id, name, kind), state in old_globals.items()
                                             if service_id == destination.id and kind == "tool"}
    moved_names = {name for _, names in sources for name in names}
    origin_connections = {source.id: [row for row in connections if row.service_id == source.id] for source, _ in sources}
    for source, names in sources:
        _require_plain_service(source)
        if any(row.singleton_key != 0 for row in origin_connections[source.id]):
            raise ValueError(f"Cannot merge {source.code}: more than one connection slot may apply to an agent")
        origin_ids = {row.id for row in origin_connections[source.id]}
        await _check_references(session, source, sorted(origin_ids))
        if await session.scalar(select(ConnectionParam.id).where(ConnectionParam.connection_id.in_(origin_ids)).limit(1)):
            raise ValueError(f"Cannot merge {source.code}: a connection parameter requires an explicit destination")
        if any(kind != "tool" or name not in names for connection, name, kind in local if connection in origin_ids):
            raise ValueError(f"Cannot merge {source.code}: an unknown local policy would be lost")
        for (service_id, name, kind), policy in global_rules.items():
            if service_id != source.id:
                continue
            if kind != "tool" or name not in names:
                raise ValueError(f"Cannot merge {source.code}: an unknown global policy would be lost")
            if name in destination_globals and destination_globals[name] != _state(policy):
                raise ValueError(f"Cannot merge {source.code}: conflicting global policy for {name}")
            # Audio was opt-in for each agent. An enabled global rule only
            # applied to active Audio connections, even when creating agents.
            if source.code == "audio" and _state(policy) != "disabled":
                continue
            if name not in destination_globals:
                policy.service_id = destination.id
                destination_globals[name] = _state(policy)

    for agent_id in sorted(agent_ids):
        target = by_service_agent.get((destination.id, agent_id))
        originals = [(source, names, by_service_agent.get((source.id, agent_id))) for source, names in sources]
        incoming_active = any(origin is not None and origin.active for _, _, origin in originals)
        activate = agent_id in live_agents and incoming_active and (target is None or not target.active)
        if target is None:
            target = Connection(service_id=destination.id, agent_id=agent_id, active=activate)
            session.add(target)
            by_service_agent[destination.id, agent_id] = target
            await session.flush()
        elif activate:
            target.active = True
        if activate:
            for name in defaults.keys() - moved_names:
                _preserve_function_state(session, target, name, "disabled", local, destination_globals, defaults)
        for source, names, origin in originals:
            if origin is None and agent_id not in live_agents:
                continue
            for name in names:
                previous: State
                policy = local.get((origin.id, name, "tool")) if origin is not None else None
                inherited = old_globals.get((source.id, name, "tool"), original_defaults[name])
                if origin is not None and origin.active:
                    previous = _state(policy) if policy is not None else inherited
                elif policy is not None and _state(policy) != "disabled":
                    if target.active:
                        raise ValueError(f"Cannot merge {source.code}: activating an inactive function rule for {name}")
                    previous = _state(policy)
                else:
                    previous = "disabled"
                _preserve_function_state(session, target, name, previous, local, destination_globals, defaults,
                                         explicit=policy is not None)

    for source, names in sources:
        origin_ids = [row.id for row in origin_connections[source.id]]
        await rebind_action_history(session, source.id, {name: destination.id for name in names}, by_service_agent,
                                    origin_ids=origin_ids)
        await session.flush()
        await session.execute(delete(Connection).where(Connection.id.in_(origin_ids)))
        await session.delete(source)
    await session.flush()


def _preserve_function_state(
    session: AsyncSession, target: Connection, name: str, state: State,
    local: dict[tuple[int, str, str], ConnectionFunctionState], inherited: dict[str, State], defaults: dict[str, State],
    *, explicit: bool = False,
) -> None:
    existing = local.get((target.id, name, "tool"))
    if existing is not None:
        if _state(existing) != state:
            raise ValueError(f"Conflicting local policies for {name} on the destination connection")
    elif explicit or state != inherited.get(name, defaults[name]):
        session.add(ConnectionFunctionState(connection_id=target.id, function_name=name, state=state,
                                            enabled=state == "enabled"))


def _require_plain_service(source: Service) -> None:
    if any((source.global_params, source.icon, source.catalog, source.mcp_config, source.rest_config,
            source.file_share_config, source.messenger_config, source.listener_config,
            source.mail_config, source.calendar_config, source.task_config, any(source.conversation_tools.values()))):
        raise ValueError(f"Cannot merge {source.code}: custom Service settings require an explicit destination")


async def rebind_action_history(
    session: AsyncSession, origin_service_id: int, targets: dict[str, int],
    destinations: dict[tuple[int, int], Connection], *, origin_ids: list[int] | None = None,
) -> None:
    source = ActionAuthorization.service_id == origin_service_id
    if origin_ids is not None:
        source |= ActionAuthorization.connection_id.in_(origin_ids)
    for action in await session.scalars(select(ActionAuthorization).where(
        source, ActionAuthorization.capability_kind == "tool",
        ActionAuthorization.capability_name.in_(targets),
    ).with_for_update()):
        if action.status == "executing" or (action.status in {"pending", "approved"} and not action.has_expired(datetime.now(timezone.utc))):
            raise ValueError(f"Cannot move {action.capability_name}: an action authorization is still in progress")
        service_id = targets[action.capability_name]
        destination = destinations.get((service_id, action.agent_id))
        if destination is None:
            destination = Connection(service_id=service_id, agent_id=action.agent_id, active=False)
            session.add(destination)
            destinations[service_id, action.agent_id] = destination
            await session.flush()
        action.service_id = service_id
        action.connection_id = destination.id


async def _merge_service(
    session: AsyncSession, source: Service, targets: dict[str, Service],
    approvals: dict[str, Literal["enabled", "ask"]], available_defaults: set[str], galaris: Service,
) -> None:
    _require_plain_service(source)
    origins = list(await session.scalars(select(Connection).where(Connection.service_id == source.id).with_for_update()))
    origin_ids = [connection.id for connection in origins]
    target_ids = {target.id for target in targets.values()}
    destinations = {(connection.service_id, connection.agent_id): connection
                    for connection in await session.scalars(select(Connection).where(
                        Connection.service_id.in_(target_ids), Connection.singleton_key == 0))}
    await _check_references(session, source, origin_ids)
    # The ordinary dataset omits soft-deleted agents. Keep their settings on
    # inactive destination connections so a later restore can recover them.
    missing = {(service_id, origin.agent_id) for origin in origins for service_id in target_ids} - destinations.keys()
    if missing:
        archived = set(await session.scalars(select(Agent.id).where(
            Agent.id.in_({agent_id for _, agent_id in missing}), Agent.deleted_at.is_not(None),
        ).execution_options(include_historized=True)))
        for service_id, agent_id in sorted(missing):
            target = Connection(service_id=service_id, agent_id=agent_id, active=agent_id not in archived)
            session.add(target)
            destinations[service_id, agent_id] = target
        await session.flush()

    inherited: dict[str, State] = {}
    destination_globals = {(row.service_id, row.function_name): row for row in await session.scalars(
        select(ServiceFunctionState).where(ServiceFunctionState.service_id.in_(target_ids),
                                           ServiceFunctionState.capability_kind == "tool"),
    )}
    for row in await session.scalars(select(ServiceFunctionState).where(ServiceFunctionState.service_id == source.id)):
        if row.capability_kind != "tool" or row.function_name not in targets:
            raise ValueError(f"Cannot merge {source.code}: an unknown global function policy would be lost")
        inherited[row.function_name] = _state(row)
        if _state(row) == "disabled":
            target_id = targets[row.function_name].id
            current = destination_globals.get((target_id, row.function_name))
            if current is None:
                session.add(ServiceFunctionState(service_id=target_id, function_name=row.function_name,
                                                 enabled=False, state="disabled"))
            elif _state(current) != "disabled":
                raise ValueError(f"Cannot merge {source.code}: conflicting global policies for {row.function_name}")
        elif not any(origin.active for origin in origins):
            raise ValueError(f"Cannot merge {source.code}: an enabled global policy has no active connection")

    local: dict[int, dict[str, State]] = {}
    policies = {(row.connection_id, row.function_name): row for row in await session.scalars(
        select(ConnectionFunctionState).where(
            ConnectionFunctionState.connection_id.in_(origin_ids + [item.id for item in destinations.values()]),
            ConnectionFunctionState.capability_kind == "tool",
        ))}
    for row in await session.scalars(select(ConnectionFunctionState).where(ConnectionFunctionState.connection_id.in_(origin_ids))):
        if row.capability_kind != "tool" or row.function_name not in targets:
            raise ValueError(f"Cannot merge {source.code}: an unknown connection function policy would be lost")
        local.setdefault(row.connection_id, {})[row.function_name] = _state(row)

    origin_by_id = {connection.id: connection for connection in origins}
    for parameter in await session.scalars(select(ConnectionParam).where(ConnectionParam.connection_id.in_(origin_ids))):
        if source.code != "platform_admin" or parameter.param_name != MANAGEMENT_SCOPE_PARAM:
            raise ValueError(f"Cannot merge {source.code}: a connection parameter requires an explicit destination")
        origin = origin_by_id[parameter.connection_id]
        if not origin.active and parameter.param_value not in {None, "usage"}:
            raise ValueError("Cannot merge Administration: an inactive connection retains a delegated scope")
        target = destinations.get((galaris.id, origin.agent_id))
        if target is None:
            raise ValueError("Cannot merge Administration: a configured connection has no Galaris destination")
        existing = await session.scalar(select(ConnectionParam).where(
            ConnectionParam.connection_id == target.id, ConnectionParam.param_name == MANAGEMENT_SCOPE_PARAM,
        ))
        if existing is None:
            session.add(ConnectionParam(connection_id=target.id, param_name=MANAGEMENT_SCOPE_PARAM,
                                        param_value=parameter.param_value))
        elif (existing.param_value or "usage") != (parameter.param_value or "usage"):
            raise ValueError("Cannot merge Administration: the source and destination management scopes differ")

    for origin in origins:
        if source.code == "voice" and origin.active:
            conversation = next(iter(targets.values()))
            target = destinations.get((conversation.id, origin.agent_id))
            if target is None:
                raise ValueError("Cannot merge Voice: an active connection has no destination")
            setting = await session.scalar(select(ConnectionParam).where(
                ConnectionParam.connection_id == target.id, ConnectionParam.param_name == VOICE_AUTO_ANSWER_PARAM,
            ))
            if setting is None:
                session.add(ConnectionParam(connection_id=target.id, param_name=VOICE_AUTO_ANSWER_PARAM,
                                            param_value="true"))
            elif setting.param_value != "true":
                raise ValueError("Cannot merge Voice: conflicting auto-answer settings")
        overrides = local.get(origin.id, {})
        if not origin.active and any(value != "disabled" for value in overrides.values()):
            raise ValueError(f"Cannot merge {source.code}: an inactive connection retains an enabled function policy")
        for name, service in targets.items():
            target = destinations.get((service.id, origin.agent_id))
            if target is None:
                if name in overrides:
                    raise ValueError(f"Cannot merge {source.code}: a configured connection has no destination")
                continue
            existing = policies.get((target.id, name))
            current = destination_globals.get((service.id, name))
            if not origin.active and name not in overrides:
                if name not in available_defaults or existing is not None or current is not None:
                    continue
                state: State = "disabled"
            else:
                state = overrides.get(name, inherited.get(name, approvals[name]))
            if existing is not None:
                if _state(existing) != state:
                    raise ValueError(f"Cannot merge {source.code}: conflicting policies for {name}")
                continue
            if current is not None and inherited.get(name) != _state(current) and _state(current) != state:
                raise ValueError(f"Cannot merge {source.code}: conflicting global policies for {name}")
            session.add(ConnectionFunctionState(connection_id=target.id, function_name=name,
                                                enabled=state == "enabled", state=state))

    for action in await session.scalars(select(ActionAuthorization).where(
        (ActionAuthorization.service_id == source.id) | ActionAuthorization.connection_id.in_(origin_ids),
    ).with_for_update()):
        if action.status == "executing" or (action.status in {"pending", "approved"} and not action.has_expired(datetime.now(timezone.utc))):
            raise ValueError(f"Cannot merge {source.code}: an action authorization is still in progress")
        service = targets.get(action.capability_name)
        if service is not None:
            action.service_id = service.id
            destination = destinations.get((service.id, action.agent_id))
            action.connection_id = destination.id if destination else None

    await session.flush()
    await session.execute(delete(Connection).where(Connection.id.in_(origin_ids)))
    await session.delete(source)
    await session.flush()
