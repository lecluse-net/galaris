"""Shared write-only Service projections for HTTP and delegated administration."""

from .assertions import service_can_edit
from .rest_contracts import RestConfig
from .protocols import ProtocolConfig
from .capabilities import effective_capabilities
from . import service
from .models import Service as ServiceModel
from .schemas import (
    ConnectionSchema,
    FileShareConfig,
    ListenerConfigPublic,
    MessengerConfig,
    McpConfigPublic,
    TaskConfig,
    ServicePublic,
    ServiceCatalogMetadata,
    ServiceIcon,
)
from .secrets import (
    public_connection_schema,
    public_listener_config,
    public_messenger_config,
    public_mcp_config,
)

def to_public(record: ServiceModel) -> ServicePublic:
    mcp_config = record.mcp_config
    listener_config = record.listener_config
    messenger_config = record.messenger_config
    return ServicePublic(
        id=record.id,
        code=record.code,
        label=record.label,
        description=record.description or "",
        icon=ServiceIcon.model_validate(record.icon) if record.icon else None,
        catalog=ServiceCatalogMetadata.model_validate(record.catalog) if record.catalog else None,
        capabilities=effective_capabilities(record),
        # Legacy native packages may still contain ``{}`` until the upgrade
        # backfill runs. An empty object is not a configurable MCP server.
        has_mcp=bool(mcp_config),
        has_api=record.rest_config is not None,
        has_mail=record.mail_config is not None,
        has_calendar=record.calendar_config is not None or record.code == "calendar",
        mail_config=ProtocolConfig.model_validate(record.mail_config) if record.mail_config is not None else None,
        calendar_config=ProtocolConfig.model_validate(record.calendar_config) if record.calendar_config is not None else None,
        rest_config=RestConfig.model_validate(record.rest_config) if record.rest_config else None,
        has_file_share=record.file_share_config is not None,
        has_messenger=messenger_config is not None,
        has_listener=listener_config is not None,
        can_edit=service_can_edit(record),
        can_disable=record.can_disable,
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
                    secret_fields=service.messenger_secret_fields(
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
        connection_schema=ConnectionSchema(**public_connection_schema(service.connection_schema_for_service(record))),
        global_params=service.public_global_params(record),
        task_config=TaskConfig(**record.task_config) if record.task_config else None,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
