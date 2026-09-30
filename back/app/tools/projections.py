"""Shared write-only Tool projections for HTTP and delegated administration."""

from .assertions import tool_can_edit
from . import tool_service
from .models import Tool as ToolModel
from .schemas import (
    ConnectionSchema,
    FileShareConfig,
    ListenerConfigPublic,
    MessengerConfig,
    McpConfigPublic,
    TaskConfig,
    ToolPublic,
)
from .secrets import (
    public_connection_schema,
    public_listener_config,
    public_messenger_config,
    public_mcp_config,
)

def to_public(record: ToolModel) -> ToolPublic:
    mcp_config = record.mcp_config
    listener_config = record.listener_config
    messenger_config = record.messenger_config
    return ToolPublic(
        id=record.id,
        code=record.code,
        label=record.label,
        description=record.description or "",
        # Legacy native packages may still contain ``{}`` until the upgrade
        # backfill runs. An empty object is not a configurable MCP server.
        has_mcp=bool(mcp_config),
        has_file_share=record.file_share_config is not None,
        has_messenger=messenger_config is not None,
        has_listener=listener_config is not None,
        can_edit=tool_can_edit(record),
        can_disable=record.can_disable,
        conversation_enabled=bool(record.conversation_enabled),
        mcp_config=(
            McpConfigPublic(**public_mcp_config(mcp_config))
            if mcp_config
            else None
        ),
        file_share_config=FileShareConfig(**record.file_share_config) if record.file_share_config else None,
        messenger_config=(
            MessengerConfig(
                **public_messenger_config(
                    messenger_config,
                    secret_fields=tool_service.messenger_secret_fields(
                        str(messenger_config.get("service") or "")
                    ),
                )
            )
            if messenger_config
            else None
        ),
        listener_config=(
            ListenerConfigPublic(**public_listener_config(listener_config))
            if listener_config
            else None
        ),
        connection_schema=(
            ConnectionSchema(
                **public_connection_schema(record.connection_schema)
            )
            if record.connection_schema
            else ConnectionSchema()
        ),
        global_params=tool_service.public_global_params(record),
        task_config=TaskConfig(**record.task_config) if record.task_config else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
