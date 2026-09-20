from __future__ import annotations

from typing import Any, Dict, Optional

import yaml

from core.authorize import BaseAssertion, AssertionContext
from core.util import as_dict

from .models import Tool as ToolModel
from .mandatory_tools import INTEGRATED_TOOL_CODES


READ_ONLY_TOOL_CODES = frozenset({"app", *INTEGRATED_TOOL_CODES})


def tool_can_edit(record_or_code: ToolModel | str | None) -> bool:
    """Return whether administration routes may edit a tool."""
    if isinstance(record_or_code, ToolModel) and record_or_code.can_disable is False:
        return False
    code = (
        record_or_code.code
        if isinstance(record_or_code, ToolModel)
        else str(record_or_code or "")
    )
    return code not in READ_ONLY_TOOL_CODES


class ToolCanEditAssertion(BaseAssertion):
    """Prevent changes to required system tools."""

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        return tool_can_edit(entity)

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        tool_id = params.get("tool_id")
        if tool_id is not None:
            return await self._assert_tool_id(tool_id, context)

        if route_name == "import_tool":
            return await self._assert_import(params, context)

        code = str(params.get("code") or "")
        return tool_can_edit(code)

    async def _assert_tool_id(self, tool_id: Any, context: AssertionContext) -> bool:
        if context.db is None:
            return False
        try:
            tool_id_int = int(tool_id)
        except (TypeError, ValueError):
            return False

        record = await context.db.get(ToolModel, tool_id_int)
        if record is None:
            return True
        return tool_can_edit(record)

    async def _assert_import(self, params: dict[str, Any], context: AssertionContext) -> bool:
        code = await self._import_tool_code(context)
        if not code:
            return True

        existing = None
        if context.db is not None:
            from sqlalchemy import select

            result = await context.db.execute(select(ToolModel).where(ToolModel.code == code))
            existing = result.scalar_one_or_none()

        overwrite = str(params.get("overwrite") or "").lower() in {"1", "true", "yes", "on"}
        if existing is None:
            return tool_can_edit(code)
        if overwrite:
            return tool_can_edit(existing)
        return True

    async def _import_tool_code(self, context: AssertionContext) -> str:
        if context.request is None:
            return ""
        try:
            raw = yaml.safe_load((await context.request.body()).decode("utf-8"))
        except Exception:
            return ""
        if not isinstance(raw, dict):
            return ""
        return str(as_dict(raw).get("code") or "")
