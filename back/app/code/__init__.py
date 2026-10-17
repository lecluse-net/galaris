"""Authorized IDE workspaces operating on the actual Console Git checkout."""

from .contracts import CodeConnection, WorkspaceTarget, CodeRuntime, CodeRuntimeNotConfiguredError, Mode, RuntimeEndpoint, RUNTIME_CONFIGURATION_LOCK_OFFSET, register_runtime, runtime
from .service import register_repository, workspace_for_agent, link_repository, workspace_context, human_repository_info, human_directory_repository, human_repository_candidates
from .contracts import RepositoryCandidates
from .resource_facade import read_code_resource, list_code_resources
from .schemas import WorkspaceInfo
from .lifecycle import reconcile_sessions
from .runtime_configuration import prepare_runtime_configuration, finish_runtime_configuration, lock_runtime_upgrade

__all__ = ["CodeConnection", "WorkspaceTarget", "CodeRuntime", "CodeRuntimeNotConfiguredError", "Mode", "RuntimeEndpoint", "register_runtime", "runtime",
           "register_repository", "workspace_for_agent", "link_repository", "workspace_context", "WorkspaceInfo",
           "read_code_resource", "list_code_resources", "reconcile_sessions", "human_repository_info", "human_directory_repository",
           "RepositoryCandidates", "human_repository_candidates",
           "prepare_runtime_configuration", "finish_runtime_configuration", "lock_runtime_upgrade", "RUNTIME_CONFIGURATION_LOCK_OFFSET"]
