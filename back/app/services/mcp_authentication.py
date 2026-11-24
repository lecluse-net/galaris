"""Retire credentials when a saved MCP authentication method changes."""

from typing import Any, cast

from core.util import SECRET_MASK

from .protocols import referenced_protocol_params
from .schemas import McpAuth, McpAuthType


def mcp_auth_mode(config: dict[str, Any] | None) -> McpAuthType:
    return McpAuth.model_validate((config or {}).get("auth") or {}).type


def mcp_secret_parameters(config: dict[str, Any] | None) -> set[str]:
    auth = McpAuth.model_validate((config or {}).get("auth") or {})
    # A migrated OAuth Service can still carry the former Bearer reference.
    if auth.type == "basic":
        return {auth.password_param}
    if auth.param and (auth.type in {"bearer", "header", "oauth"} or auth.url_param):
        return {auth.param}
    return set()


def replace_mcp_auth(
    previous: dict[str, Any], target: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, set[str]]:
    """Keep new settings and identify the previous method's parameter bindings."""
    old_auth = McpAuth.model_validate(previous.get("auth") or {})
    old_header_names = {"authorization"}
    if old_auth.type == "header":
        old_header_names.add(old_auth.header_name.lower())
    old_headers = {name.lower(): value for name, value in cast(dict[str, str], previous.get("headers") or {}).items()
                   if name.lower() in old_header_names}
    retired = mcp_secret_parameters(previous) | referenced_protocol_params(mcp_config={"headers": old_headers})
    if old_auth.type == "basic":
        retired.add(old_auth.login_param)

    if target is None:
        return None, retired
    auth = McpAuth.model_validate(target.get("auth") or {})
    if auth.type in {"none", "oauth"}:
        auth = McpAuth(type=auth.type)
    elif auth.type == "basic":
        auth = McpAuth(type="basic", login_param=auth.login_param, password_param=auth.password_param)
    if auth.token_static in {None, SECRET_MASK, old_auth.token_static}:
        # An explicit empty value prevents the write-only merge from restoring an old token.
        auth.token_static = ""
    headers = {name: value for name, value in cast(dict[str, str], target.get("headers") or {}).items()
               if name.lower() not in old_header_names or (
                   value != SECRET_MASK and value != old_headers.get(name.lower())
               )}
    return {**target, "auth": auth.model_dump(), "headers": headers}, retired
