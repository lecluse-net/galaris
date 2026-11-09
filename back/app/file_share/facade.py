"""Public read-only resource preview port for authorized domain surfaces."""

from .browser import browser_context as browser_context, browser_content as browser_content, browser_thumbnail as browser_thumbnail
from .operation_memos import (conversion_key as conversion_key, converted_resource as converted_resource,
    remember_conversion as remember_conversion, conversion_origins as conversion_origins)

from .resource_contracts import ResourceContext


async def can_inspect_source(ctx: ResourceContext, uri: str) -> bool:
    """Human domain gates and live provider ACLs compose for audit references too."""
    if ctx.management_scope is not None:
        from core.user import get_user_record
        from core.authorize import check_privilege
        from core.database import get_db
        from .browser_policy import resource_privileges
        user = await get_user_record(ctx.management_scope.user_id)
        required = resource_privileges(uri)
        if user is None or not user.is_active or not required or not await check_privilege(user, list(required), get_db()):
            return False
    from .resource_service import resource_info
    return "read" in (await resource_info(ctx, uri)).capabilities
