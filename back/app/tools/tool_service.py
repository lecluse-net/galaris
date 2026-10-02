"""Database service for MCP tools."""

from typing import Any, Dict, List, Optional, Tuple, cast

from loguru import logger
import yaml
from sqlalchemy import select

from core.database import get_db
from core.i18n import render_prompt, tr
from core.util import get_encryption_service
from .models import Tool as ToolModel
from .administration_lock import lock_tools, finish_write
from .parameter_definitions import with_standard_params
from .secrets import (
    SecretPlaceholderWithoutValue,
    export_listener_config,
    export_messenger_config,
    export_mcp_config,
    password_default_fields,
    protect_listener_config,
    protect_messenger_config,
    protect_mcp_config,
    public_connection_schema,
    runtime_listener_config,
    runtime_messenger_config,
    runtime_mcp_config,
)
from .schemas import (
    ConnectionParamDef,
    ConnectionSchema,
    FileShareConfig,
    ListenerConfig,
    MessengerConfig,
    McpConfig,
    TaskConfig,
    Tool,
    ToolCreate,
    ToolGlobalParamPublic,
    ToolGlobalParamsUpdate,
    ToolUpdate,
)


_encryption = get_encryption_service()


async def get_tool_codes(tool_ids: set[int]) -> dict[int, str]:
    """Resolve stable codes in one query without loading credentials or configuration."""
    if not tool_ids:
        return {}
    rows = await get_db().execute(select(ToolModel.id, ToolModel.code).where(ToolModel.id.in_(tool_ids)))
    return {tool_id: code for tool_id, code in rows}


def connection_schema_for_tool(record: ToolModel) -> Dict[str, Any]:
    return with_standard_params(record.connection_schema or {}, code=record.code,
                                file_share_config=record.file_share_config)


def _connection_param_definitions(record: ToolModel) -> Dict[str, Dict[str, Any]]:
    schema = connection_schema_for_tool(record)
    return cast(Dict[str, Dict[str, Any]], schema.get("params") or {})


def _global_param_entries(record: ToolModel) -> Dict[str, Dict[str, Any]]:
    return cast(Dict[str, Dict[str, Any]], record.global_params or {})


def _global_param_is_secret(definition: Dict[str, Any]) -> bool:
    return str(definition.get("type") or "string") == "password"


def default_global_params(connection_schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Seed schema defaults as editable global values for a newly initialized Tool."""

    definitions = cast(Dict[str, Dict[str, Any]], connection_schema.get("params") or {})
    result: Dict[str, Dict[str, Any]] = {}
    for name, definition in definitions.items():
        default = definition.get("default")
        value = str(default) if default not in (None, "") else None
        result[name] = {"value": value, "forced": False}
    return result


def merge_default_global_params(
    global_params: Dict[str, Any] | None,
    connection_schema: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    """Add newly declared parameters without changing administrator-owned values."""

    merged = {
        name: dict(cast(Dict[str, Any], entry))
        for name, entry in (global_params or {}).items()
        if isinstance(entry, dict)
    }
    for name, entry in default_global_params(connection_schema).items():
        merged.setdefault(name, entry)
    return merged


def public_global_params(record: ToolModel) -> Dict[str, ToolGlobalParamPublic]:
    """Return every declared parameter without exposing global secret values."""

    entries = _global_param_entries(record)
    result: Dict[str, ToolGlobalParamPublic] = {}
    for name, definition in _connection_param_definitions(record).items():
        entry = entries.get(name) or {}
        stored = entry.get("value")
        configured = isinstance(stored, str) and stored != ""
        secret = _global_param_is_secret(definition)
        result[name] = ToolGlobalParamPublic(
            value=None if secret or not configured else str(stored),
            configured=configured,
            secret=secret,
            forced=bool(entry.get("forced")) if configured else False,
        )
    return result


async def get_runtime_global_params(
    tool_id: int,
    *,
    decrypt_passwords: bool = True,
) -> tuple[Dict[str, Any], set[str]]:
    """Resolve configured Tool values and names whose global value is imposed."""

    record = await get_tool_record_by_id(tool_id)
    if record is None:
        return {}, set()
    definitions = _connection_param_definitions(record)
    values: Dict[str, Any] = {}
    forced: set[str] = set()
    for name, entry in _global_param_entries(record).items():
        definition = definitions.get(name)
        if definition is None:
            continue
        stored = entry.get("value")
        if not isinstance(stored, str) or stored == "":
            continue
        value = stored
        if decrypt_passwords and _global_param_is_secret(definition):
            value = _encryption.decrypt(stored) if _encryption.is_encrypted(stored) else stored
        values[name] = value
        if bool(entry.get("forced")):
            forced.add(name)
    return values, forced


async def update_global_params(
    tool_id: int,
    data: ToolGlobalParamsUpdate,
    *, commit: bool = True,
) -> ToolModel | None:
    """Persist administrator-owned global values without changing the Tool definition."""

    db = get_db()
    await lock_tools([tool_id], db=get_db())
    record = await db.get(ToolModel, tool_id)
    if record is None:
        return None
    if record.can_disable is False:
        raise ValueError(await tr("tools.errors.system_read_only"))
    definitions = _connection_param_definitions(record)
    unknown = sorted(set(data.params) - set(definitions))
    if unknown:
        raise ValueError(f"Unknown connection parameter(s): {', '.join(unknown)}")

    entries = {name: dict(entry) for name, entry in _global_param_entries(record).items()}
    for name, update in data.params.items():
        definition = definitions[name]
        previous = entries.get(name) or {}
        previous_value = previous.get("value")
        value: str | None
        if update.clear:
            value = None
        elif update.value is None:
            value = str(previous_value) if isinstance(previous_value, str) else None
        else:
            value = update.value if update.value.strip() else None

        from core.util import SECRET_MASK
        from app.connection.facade import validate_param_value

        if value == SECRET_MASK:
            if not previous_value:
                raise ValueError("A masked value requires an existing secret")
            value = str(previous_value)
        if value is not None:
            validate_param_value(str(definition.get("type") or "string"), value)
            options = ConnectionParamDef.model_validate(definition).options
            if options and value not in {option.value for option in options}:
                raise ValueError("Connection parameter must be one of the fixed options")

        if value is not None and _global_param_is_secret(definition):
            if not _encryption.is_encrypted(value):
                value = _encryption.encrypt(value)
        entries[name] = {
            "value": value,
            "forced": bool(update.forced and value is not None),
        }

    record.global_params = entries
    await finish_write(commit=commit, db=get_db())
    await db.refresh(record)
    logger.info(
        "Global connection parameters updated for Tool {} (fields={})",
        record.code,
        ",".join(sorted(data.params)),
    )
    return record


async def _validate_connection_schema(config: Dict[str, Any]) -> None:
    fields = password_default_fields(config)
    if fields:
        raise ValueError(
            render_prompt(
                await tr("tools.errors.password_default_forbidden"),
                fields=", ".join(fields),
            )
        )


def _messenger_secret_fields(service: str) -> frozenset[str]:
    from app.messenger import get_spec

    spec = get_spec(service)
    if spec is None:
        return frozenset()
    return frozenset(
        param.name for param in spec.tool_params if param.type == "password"
    )


messenger_secret_fields = _messenger_secret_fields


async def _validate_messenger_config(
    config: Dict[str, Any],
    connection_schema: Dict[str, Any],
) -> None:
    from app.messenger import get_spec

    service = str(config.get("service") or "")
    spec = get_spec(service)
    if spec is None:
        raise ValueError(f"Unknown Messenger bridge: {service or '<empty>'}.")
    settings = cast(Dict[str, Any], config.get("settings") or {})
    param_map = cast(Dict[str, Any], config.get("param_map") or {})
    connection_params = cast(Dict[str, Any], connection_schema.get("params") or {})
    for definition in spec.tool_params:
        if definition.required and not settings.get(definition.name):
            raise ValueError(
                f"Messenger bridge {service} requires Tool setting "
                f"{definition.name}."
            )
    for definition in spec.connection_params:
        mapped_name = str(param_map.get(definition.name) or "")
        if definition.required and not mapped_name:
            raise ValueError(
                f"Messenger bridge {service} requires a mapping for "
                f"{definition.name}."
            )
        if mapped_name and mapped_name not in connection_params:
            raise ValueError(
                f"Messenger bridge {service} maps {definition.name} to unknown "
                f"connection parameter {mapped_name}."
            )


async def _protect_messenger(
    config: Dict[str, Any],
    *,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        service = str(config.get("service") or "")
        return protect_messenger_config(
            config,
            secret_fields=_messenger_secret_fields(service),
            existing=existing,
        )
    except SecretPlaceholderWithoutValue as exc:
        raise ValueError(
            render_prompt(
                await tr("tools.errors.secret_placeholder_without_value"),
                field=exc.field,
            )
        ) from exc


async def _protect_mcp(
    config: Dict[str, Any],
    *,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        return protect_mcp_config(config, existing=existing)
    except SecretPlaceholderWithoutValue as exc:
        raise ValueError(
            render_prompt(
                await tr("tools.errors.secret_placeholder_without_value"),
                field=exc.field,
            )
        ) from exc


async def _protect_listener(
    config: Dict[str, Any],
    *,
    existing: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    try:
        return protect_listener_config(config, existing=existing)
    except SecretPlaceholderWithoutValue as exc:
        raise ValueError(
            render_prompt(
                await tr("tools.errors.secret_placeholder_without_value"),
                field=exc.field,
            )
        ) from exc


# =============================================================================
# Database record to internal schema conversion.
# =============================================================================

def _to_internal(record: ToolModel) -> Tool:
    return Tool(
        code=record.code,
        can_disable=record.can_disable,
        label=record.label,
        description=record.description or "",
        mcp_config=(
            McpConfig(**runtime_mcp_config(record.mcp_config))
            if record.mcp_config
            else None
        ),
        file_share_config=FileShareConfig(**record.file_share_config) if record.file_share_config else None,
        messenger_config=(
            MessengerConfig(
                **runtime_messenger_config(
                    record.messenger_config,
                    secret_fields=_messenger_secret_fields(
                        str(record.messenger_config.get("service") or "")
                    ),
                )
            )
            if record.messenger_config
            else None
        ),
        listener_config=(
            ListenerConfig(**runtime_listener_config(record.listener_config))
            if record.listener_config
            else None
        ),
        connection_schema=ConnectionSchema(**connection_schema_for_tool(record)),
        task_config=TaskConfig(**record.task_config) if record.task_config else None,
        conversation_enabled=bool(record.conversation_enabled),
    )


# =============================================================================
# Database CRUD.
# =============================================================================

async def create_tool(data: ToolCreate, *, commit: bool = True) -> ToolModel:
    from app.file_share import validate_external_tool_code

    validate_external_tool_code(
        data.code,
        file_share=data.file_share_config is not None,
        messenger=data.messenger_config is not None,
    )
    from .assertions import tool_can_edit

    if not tool_can_edit(data.code):
        raise ValueError("Integrated Tool definitions are software-owned")
    db = get_db()
    connection_schema = with_standard_params(data.connection_schema.model_dump(), code=data.code,
        file_share_config=data.file_share_config.model_dump() if data.file_share_config else None)
    await _validate_connection_schema(connection_schema)
    messenger_config = (
        data.messenger_config.model_dump() if data.messenger_config else None
    )
    if messenger_config is not None:
        await _validate_messenger_config(messenger_config, connection_schema)
    record = ToolModel(
        code=data.code,
        label=data.label,
        description=data.description,
        mcp_config=(
            await _protect_mcp(data.mcp_config.model_dump())
            if data.mcp_config
            else None
        ),
        file_share_config=data.file_share_config.model_dump() if data.file_share_config else None,
        messenger_config=(
            await _protect_messenger(messenger_config)
            if messenger_config is not None
            else None
        ),
        listener_config=(
            await _protect_listener(data.listener_config.model_dump())
            if data.listener_config
            else None
        ),
        connection_schema=connection_schema,
        global_params=default_global_params(connection_schema),
        task_config=data.task_config.model_dump() if data.task_config else None,
        conversation_enabled=data.conversation_enabled,
    )
    if not record.description.strip():
        from .descriptions import bridge_description

        record.description = bridge_description(record.messenger_config, record.file_share_config)
    db.add(record)
    await finish_write(commit=commit, db=get_db())
    await db.refresh(record)
    from .mandatory_tools import AUTO_CONNECTED_INTEGRATED_TOOL_CODES, sync_integrated_tool_connections

    if record.code in AUTO_CONNECTED_INTEGRATED_TOOL_CODES:
        await sync_integrated_tool_connections()
        await finish_write(commit=commit, db=get_db())
        await db.refresh(record)
    return record


async def update_tool(tool_id: int, data: ToolUpdate, *, commit: bool = True) -> Optional[ToolModel]:
    from app.file_share import validate_external_tool_code
    from .mandatory_tools import INTEGRATED_TOOL_CODES

    db = get_db()
    await lock_tools([tool_id], db=get_db())
    record = await db.get(ToolModel, tool_id)
    if not record:
        return None

    from .assertions import tool_can_edit

    if not tool_can_edit(record):
        raise ValueError(await tr("tools.errors.system_read_only"))

    # ``model_fields_set`` distinguishes omitted fields from explicit null values so overwrite
    # imports can remove old optional configuration.
    values = data.model_dump()
    target_connection_schema = cast(
        Dict[str, Any],
        values.get("connection_schema")
        if "connection_schema" in data.model_fields_set
        and values.get("connection_schema") is not None
        else record.connection_schema,
    )
    target_messenger_config = cast(
        Dict[str, Any] | None,
        values.get("messenger_config")
        if "messenger_config" in data.model_fields_set
        else record.messenger_config,
    )
    target_file_share_config = (
        values.get("file_share_config")
        if "file_share_config" in data.model_fields_set
        else record.file_share_config
    )
    if (
        record.code not in INTEGRATED_TOOL_CODES
        or target_file_share_config is not None
        or target_messenger_config is not None
    ):
        validate_external_tool_code(
            record.code,
            file_share=target_file_share_config is not None,
            messenger=target_messenger_config is not None,
        )
    if target_messenger_config is not None:
        await _validate_messenger_config(
            target_messenger_config,
            target_connection_schema,
        )
    for field in data.model_fields_set:
        value = values[field]
        # Preserve non-nullable text fields when a client explicitly sends null.
        if field in {"label", "description"} and value is None:
            continue
        if field == "mcp_config" and value is not None:
            value = await _protect_mcp(
                cast(Dict[str, Any], value),
                existing=record.mcp_config,
            )
        elif field == "listener_config" and value is not None:
            value = await _protect_listener(
                cast(Dict[str, Any], value),
                existing=record.listener_config,
            )
        elif field == "messenger_config" and value is not None:
            value = await _protect_messenger(
                cast(Dict[str, Any], value),
                existing=record.messenger_config,
            )
        elif field == "connection_schema" and value is not None:
            connection_schema = cast(Dict[str, Any], value)
            await _validate_connection_schema(connection_schema)
        setattr(record, field, value)
    if {"connection_schema", "file_share_config"} & data.model_fields_set:
        record.connection_schema = connection_schema_for_tool(record)
        record.global_params = merge_default_global_params(
            record.global_params,
            record.connection_schema,
        )
    await finish_write(commit=commit, db=get_db())
    await db.refresh(record)
    return record


async def update_conversation_access(
    tool_id: int, *, enabled: bool, commit: bool = True
) -> Optional[ToolModel]:
    """Update the independent conversation projection switch."""

    await lock_tools([tool_id], db=get_db())
    record = await get_db().get(ToolModel, tool_id)
    if record is None:
        return None
    if record.can_disable is False:
        raise ValueError(await tr("tools.errors.system_read_only"))
    record.conversation_enabled = enabled
    await finish_write(commit=commit, db=get_db())
    await get_db().refresh(record)
    return record


async def delete_tool(tool_id: int, *, commit: bool = True) -> bool:
    db = get_db()
    await lock_tools([tool_id], db=get_db())
    record = await db.get(ToolModel, tool_id)
    if not record:
        return False
    from .assertions import tool_can_edit

    if not tool_can_edit(record):
        raise ValueError(await tr("tools.errors.system_read_only"))
    from app.connection.facade import get_agent_ids_by_tool, administration

    if await get_agent_ids_by_tool(tool_id) or await administration.references([], tool_id=tool_id):
        raise ValueError("This Tool still has dependencies")
    await db.delete(record)
    await finish_write(commit=commit, db=get_db())
    return True


async def get_tool_record(code: str) -> Optional[ToolModel]:
    db = get_db()
    result = await db.execute(select(ToolModel).where(ToolModel.code == code).execution_options(populate_existing=True))
    return result.scalar_one_or_none()


async def get_tool_record_by_id(tool_id: int) -> Optional[ToolModel]:
    db = get_db()
    return await db.scalar(select(ToolModel).where(ToolModel.id == tool_id).execution_options(populate_existing=True))


async def get_all_tool_records() -> List[ToolModel]:
    db = get_db()
    result = await db.execute(select(ToolModel).order_by(ToolModel.code))
    return list(result.scalars().all())


# =============================================================================
# Public service interface.
# =============================================================================

async def get_tool(code: str) -> Optional[Tool]:
    record = await get_tool_record(code)
    if not record:
        return None
    return _to_internal(record)


async def get_all_tools() -> Dict[str, Tool]:
    records = await get_all_tool_records()
    return {r.code: _to_internal(r) for r in records}


async def list_tool_codes() -> List[str]:
    db = get_db()
    result = await db.execute(select(ToolModel.code).order_by(ToolModel.code))
    return list(result.scalars().all())


async def has_tool(code: str) -> bool:
    return await get_tool_record(code) is not None


async def get_tool_by_id(tool_id: int) -> Optional[Tool]:
    record = await get_tool_record_by_id(tool_id)
    if not record:
        return None
    return _to_internal(record)


# =============================================================================
# Export / Import YAML
# =============================================================================

def _record_to_export_dict(record: ToolModel) -> Dict[str, object]:
    """Serialize a tool record without exporting any write-only value."""
    d: Dict[str, object] = {"code": record.code, "label": record.label}
    if record.description:
        d["description"] = record.description
    if record.mcp_config:
        d["mcp_config"] = export_mcp_config(record.mcp_config)
    if record.file_share_config:
        d["file_share_config"] = record.file_share_config
    if record.messenger_config:
        service = str(record.messenger_config.get("service") or "")
        d["messenger_config"] = export_messenger_config(
            record.messenger_config,
            secret_fields=_messenger_secret_fields(service),
        )
    if record.listener_config:
        d["listener_config"] = export_listener_config(record.listener_config)
    schema = connection_schema_for_tool(record)
    if schema.get("params"):
        d["connection_schema"] = public_connection_schema(schema)
    if record.task_config:
        # Normalize persisted legacy JSON through the current public contract so
        # removed fields cannot reappear in exported YAML.
        d["task_config"] = TaskConfig(**record.task_config).model_dump()
    # SQLAlchemy column defaults apply on flush. Coercion also supports transient records
    # constructed by import/export callers before they have reached a session.
    d["conversation_enabled"] = bool(record.conversation_enabled)
    return d


def serialize_to_yaml(record: ToolModel) -> str:
    """Return exportable YAML content for a tool."""
    return cast(str, yaml.dump(  # type: ignore[call-overload]
        _record_to_export_dict(record),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ))


async def import_from_yaml_string(
    content: str,
    overwrite: bool = False,
) -> Tuple[ToolModel, bool]:
    """Parse YAML and create or replace a database tool.

    Returns the record and whether it was newly created.
    """
    try:
        raw: Any = yaml.safe_load(content)  # type: ignore[call-overload]
    except yaml.YAMLError as exc:
        raise ValueError(await tr("tools.errors.invalid_yaml")) from exc

    if not isinstance(raw, dict):
        raise ValueError(await tr("tools.errors.yaml_mapping_required"))

    data: Dict[str, Any] = cast(Dict[str, Any], raw)
    code = str(data.get("code", ""))
    if not code:
        raise ValueError(await tr("tools.errors.code_missing"))

    existing = await get_tool_record(code)
    if existing and not overwrite:
        raise LookupError(
            render_prompt(
                await tr("tools.errors.tool_exists"),
                code=code,
            )
        )

    tool_data = ToolCreate(**data)  # type: ignore[arg-type]
    from app.file_share import validate_external_tool_code
    from .mandatory_tools import INTEGRATED_TOOL_CODES

    if (
        existing is None
        or tool_data.code not in INTEGRATED_TOOL_CODES
        or tool_data.file_share_config is not None
        or tool_data.messenger_config is not None
    ):
        validate_external_tool_code(
            tool_data.code,
            file_share=tool_data.file_share_config is not None,
            messenger=tool_data.messenger_config is not None,
        )

    if existing:
        # Build the update from the complete schema so future fields are not omitted. Optional
        # nulls are included to mirror imported YAML exactly.
        update = ToolUpdate(**tool_data.model_dump(exclude={"code"}))
        updated = await update_tool(existing.id, update)
        return updated, False  # type: ignore[return-value]

    created = await create_tool(tool_data)
    return created, True
