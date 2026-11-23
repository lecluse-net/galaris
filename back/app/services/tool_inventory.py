"""Read-only service and tool inventory for development instances."""

from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from app.connection.facade import EffectiveFunctionState, list_service_tool_policies
from core.database import get_db

from . import service
from .mandatory_services import (
    AUTO_CONNECTED_INTEGRATED_SERVICE_CODES,
    DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES,
    INTEGRATED_SERVICE_CODES,
)
from .mcp_loader import BUILTIN_CONVERSATION_TOOLS, mcp_tools_by_service_code, native_service_codes_for_service
from .models import Service
from .schemas import ConnectionSchema, ServiceGlobalParamPublic, ServiceIcon
from .secrets import public_connection_schema


class InventoryTool(BaseModel):
    name: str
    description: str
    conversation_enabled: bool
    default_state: EffectiveFunctionState
    service_override: EffectiveFunctionState | None = None


class ServiceToolInventory(BaseModel):
    code: str
    label: str
    icon: ServiceIcon | None
    connection_default: Literal["active", "inactive", "manual"]
    connection_schema: ConnectionSchema
    global_params: dict[str, ServiceGlobalParamPublic]
    tools: list[InventoryTool]


async def read_tool_inventory() -> list[ServiceToolInventory]:
    records = (await get_db().scalars(
        select(Service).where(Service.code.in_(INTEGRATED_SERVICE_CODES)).order_by(Service.code)
    )).all()
    policies = await list_service_tool_policies([record.id for record in records])
    definitions = mcp_tools_by_service_code()
    inventory: list[ServiceToolInventory] = []
    for record in records:
        native = {
            tool.name: tool
            for code in native_service_codes_for_service(record)
            for tool in definitions.get(code, ())
        }
        overrides = policies.get(record.id, {})
        native_open = BUILTIN_CONVERSATION_TOOLS.get(record.code, ())
        tools = [
            InventoryTool(
                name=name,
                description=tool.description,
                conversation_enabled=name in native_open and tool.conversation_policy != "forbidden",
                default_state=tool.default_state, service_override=overrides.get(name),
            )
            for name, tool in sorted(native.items())
        ]
        inventory.append(ServiceToolInventory(
            code=record.code, label=record.label,
            icon=ServiceIcon.model_validate(record.icon) if record.icon else None,
            connection_default=(
                "active" if record.code in DEFAULT_ACTIVE_INTEGRATED_SERVICE_CODES else
                "inactive" if record.code in AUTO_CONNECTED_INTEGRATED_SERVICE_CODES else "manual"
            ),
            connection_schema=ConnectionSchema.model_validate(
                public_connection_schema(service.connection_schema_for_service(record))
            ),
            global_params=service.public_global_params(record),
            tools=tools,
        ))
    return inventory
