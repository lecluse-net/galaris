from app.document.router import remove_document_grant, router, set_document_grant
from core.authorize import Privileges
from app.document.router import read_document_sharing, update_document_sharing


def test_document_owner_sharing_routes_are_rbac_protected() -> None:
    route_methods = {
        (getattr(route, "path", ""), method)
        for route in router.routes
        for method in getattr(route, "methods", set())
    }

    path = "/documents/{document_id}/grants/{agent_id}"
    assert (path, "PUT") in route_methods
    assert (path, "DELETE") in route_methods
    assert set_document_grant._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.DOCUMENT_EDIT,
        Privileges.DOCUMENT_ADMIN,
    ]
    assert remove_document_grant._authorize_meta["privileges"] == [  # pyright: ignore[reportFunctionMemberAccess]
        Privileges.DOCUMENT_EDIT,
        Privileges.DOCUMENT_ADMIN,
    ]


def test_memory_sharing_requires_read_privileges_and_mutations_require_edit_privileges() -> None:
    assert read_document_sharing._authorize_meta["privileges"] == [
        Privileges.DOCUMENT_ACCESS, Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN,
    ]
    assert update_document_sharing._authorize_meta["privileges"] == [
        Privileges.DOCUMENT_EDIT, Privileges.DOCUMENT_ADMIN,
    ]
