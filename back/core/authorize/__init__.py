# Authorization module — Advanced RBAC
# Public API exports

# Context variables (leaf module, no dependencies — imported first to keep
# the public API available even during circular import resolution)
from .context import role_id_ctx, assignment_id_ctx

# Models
from .models import Role, Privilege, PrivilegeList, RolePrivilege, Assignment

# Assertions
from .assertions import (
    AssertionContext,
    BaseAssertion,
    EntityAssertion,
    CompositeAssertion,
    OwnUserOrPrivilegeAssertion,
    RequireAllPrivilegesAssertion,
)

# Decorators
from .decorators import authorize, independent_auth, public

# Services
from .authorize_service import AuthorizeService
from .privilege_service import PrivilegeService
from .update_admin_role import update_admin_role
from .logic import check_privilege
from .admin_guard import AdministratorConflictError, preserve_administrator

# Providers
from .guard_provider import GuardProvider, GuardConfig, global_authorization_guard
from .resource_rules import RuleProvider, ResourceRule

# Model scanner
from .model_scanner import scan_models, _get_all_subclasses  # pyright: ignore[reportPrivateUsage]

# Privileges (auto-generated, may not exist yet)
try:
    from .definitions import Privileges
except ImportError:
    pass


__all__ = [
    "AdministratorConflictError",
    "preserve_administrator",
    "role_id_ctx",
    "assignment_id_ctx",
    "Role",
    "Privilege",
    "PrivilegeList",
    "RolePrivilege",
    "Assignment",
    "AssertionContext",
    "BaseAssertion",
    "EntityAssertion",
    "CompositeAssertion",
    "OwnUserOrPrivilegeAssertion",
    "RequireAllPrivilegesAssertion",
    "authorize",
    "independent_auth",
    "public",
    "AuthorizeService",
    "PrivilegeService",
    "update_admin_role",
    "check_privilege",
    "GuardProvider",
    "GuardConfig",
    "global_authorization_guard",
    "RuleProvider",
    "ResourceRule",
    "scan_models",
    "_get_all_subclasses",
    "Privileges",
]
