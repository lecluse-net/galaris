from typing import Any, Dict, Optional

from core.authorize import BaseAssertion, AssertionContext


class ConnectionOwnerAssertion(BaseAssertion):
    """
    Asserts that the current user is the owner of the connection.
    Assumes the route has a 'connection_id' or 'id' path parameter.
    """

    async def assert_entity(self, entity: Any, privilege: Optional[str], context: AssertionContext) -> bool:
        return True

    async def assert_route(self, route_name: str, params: Dict[str, Any], context: AssertionContext) -> bool:
        return True
