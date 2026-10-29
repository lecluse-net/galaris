"""Public Dataset actors, access decisions and domain errors."""

from dataclasses import dataclass

from app.agent import AgentManagementScope
from core.user import HumanActor

DataActor = int | HumanActor | AgentManagementScope


class DatasetConflictError(RuntimeError):
    """Reread the resource before changing the request."""


class DatasetPermissionError(PermissionError):
    """The live actor has no authority for the requested operation."""


class DatasetNotFoundError(FileNotFoundError):
    """No accessible resource exists under the requested identity."""


class DatasetWriteLimitError(RuntimeError):
    """The shared user/Dataset write window is exhausted."""


@dataclass(frozen=True, slots=True)
class DatasetAccess:
    can_read: bool
    can_write: bool
    can_manage: bool = False
