"""Composition registration for the independently deployed code-server broker."""

from app.code import register_runtime, read_code_resource, list_code_resources
from app.file_share import register_code_resource_provider
from .adapter import CodeServerRuntime
from .deployment import deploy_connection_code_editor
from app.console import register_editor_installer

register_runtime(CodeServerRuntime())
register_editor_installer(deploy_connection_code_editor)
register_code_resource_provider(read_code_resource, list_code_resources)
