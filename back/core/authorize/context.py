from contextvars import ContextVar
from typing import Optional

# Context variables for the current RBAC role and assignment.
role_id_ctx: ContextVar[Optional[int]] = ContextVar("role_id_ctx", default=None)
assignment_id_ctx: ContextVar[Optional[int]] = ContextVar("assignment_id_ctx", default=None)
