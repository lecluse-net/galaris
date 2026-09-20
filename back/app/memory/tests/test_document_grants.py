from app.memory.router import remove_document_grant, router, set_document_grant
from core.authorize import Privileges
from app.memory.router import read_item_sharing, update_item_sharing


def test_document_owner_sharing_routes_are_rbac_protected() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    path = "/memory/documents/{document_id}/grants/{agent_id}"
    assert (path, "PUT") in route_methods
    assert (path, "DELETE") in route_methods
    assert set_document_grant._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]
    assert remove_document_grant._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.MEMORY_EDIT,
        Privileges.MEMORY_ADMIN,
    ]


def test_memory_sharing_requires_read_privileges_and_mutations_require_edit_privileges() -> None:
    assert read_item_sharing._authorize_meta["privileges"] == [
        Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN,
    ]
    assert update_item_sharing._authorize_meta["privileges"] == [
        Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN,
    ]
