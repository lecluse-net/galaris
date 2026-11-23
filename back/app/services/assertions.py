from __future__ import annotations

from typing import Any, Dict, Optional

import yaml

from core.authorize import BaseAssertion, AssertionContext
from core.util import as_dict

from .models import Service as ServiceModel
from .mandatory_services import INTEGRATED_SERVICE_CODES


READ_ONLY_TOOL_CODES = frozenset({
    "app", "skill_management", "agent_admin", "service_admin", "goal_management", "process_admin",
    "galaris_admin", "platform_admin", "voice", "audio", "image", "search", "agenda", "conversation",
    *INTEGRATED_SERVICE_CODES,
})


def service_can_edit(record_or_code: ServiceModel | str | None) -> bool:
    """Return whether administration routes may edit a tool."""
    if isinstance(record_or_code, ServiceModel) and record_or_code.can_disable is False:
        return False
    code = (
        record_or_code.code
        if isinstance(record_or_code, ServiceModel)
        else str(record_or_code or "")
    )
    return code not in READ_ONLY_TOOL_CODES


class ServiceCanEditAssertion(BaseAssertion):
    """Prevent changes to required system tools."""

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        return service_can_edit(entity)

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        service_id = params.get("service_id")
        if service_id is not None:
            return await self._assert_service_id(service_id, context)

        if route_name == "import_service":
            return await self._assert_import(params, context)

        code = str(params.get("code") or "")
        return service_can_edit(code)

    async def _assert_service_id(self, service_id: Any, context: AssertionContext) -> bool:
        if context.db is None:
            return False
        try:
            service_id_int = int(service_id)
        except (TypeError, ValueError):
            return False

        record = await context.db.get(ServiceModel, service_id_int)
        if record is None:
            return True
        return service_can_edit(record)

    async def _assert_import(self, params: dict[str, Any], context: AssertionContext) -> bool:
        code = await self._import_service_code(context)
        if not code:
            return True

        existing = None
        if context.db is not None:
            from sqlalchemy import select

            result = await context.db.execute(select(ServiceModel).where(ServiceModel.code == code))
            existing = result.scalar_one_or_none()

        overwrite = str(params.get("overwrite") or "").lower() in {"1", "true", "yes", "on"}
        if existing is None:
            return service_can_edit(code)
        if overwrite:
            return service_can_edit(existing)
        return True

    async def _import_service_code(self, context: AssertionContext) -> str:
        if context.request is None:
            return ""
        try:
            raw = yaml.safe_load((await context.request.body()).decode("utf-8"))
        except Exception:
            return ""
        if not isinstance(raw, dict):
            return ""
        return str(as_dict(raw).get("code") or "")
