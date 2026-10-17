"""Application-wide sharing; domain services authorize and retain ownership."""

from .contracts import (
    Collaborator,
    GrantUpdate,
    PrincipalKind,
    ShareKind,
    SharingConflictError,
    SharingState,
    SharingUpdate,
    SingleGrantUpdate,
)
from .models import ShareConfig, ShareGrant, Shareable, ShareReference
from .directory import directory as sharing_directory, register_sharing_directory
from .service import (
    grants as sharing_grants,
    state as sharing_state,
    replace as replace_sharing,
    set_grant,
)
from .migration import transfer as transfer_legacy_sharing, transfer_resource_acl
from .access import Principals, permission_clause as sharing_permission_clause

__all__ = [
    "Collaborator",
    "GrantUpdate",
    "PrincipalKind",
    "ShareKind",
    "SharingConflictError",
    "SharingState",
    "SharingUpdate",
    "SingleGrantUpdate",
    "ShareConfig",
    "ShareGrant",
    "Shareable",
    "ShareReference",
    "sharing_directory",
    "register_sharing_directory",
    "sharing_grants",
    "sharing_state",
    "replace_sharing",
    "set_grant",
    "transfer_legacy_sharing",
    "transfer_resource_acl",
    "Principals",
    "sharing_permission_clause",
]
