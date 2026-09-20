"""English authorization API messages."""

default = {
    "authorize_api": {
        "errors": {
            "privilege_code_exists": "Privilege code already exists",
            "privilege_not_found": "Privilege not found",
            "role_code_exists": "Role code already exists",
            "role_not_found": "Role not found",
            "assignment_exists": "Assignment already exists",
            "assignment_not_found": "Assignment not found",
            "not_authenticated": "Not authenticated",
            "route_not_declared": "Route authorization is not configured",
            "inactive_user": "Inactive user",
            "missing_privilege": "Missing privilege: ${privileges}",
            "assertion_denied": "Access denied by assertion rule",
            "role_not_owned": "You do not have this role",
            "own_assignments_only": "You may only modify your own assignments",
            "list_exists": "A list with this name already exists",
            "list_not_found": "List not found",
        },
    },
}
