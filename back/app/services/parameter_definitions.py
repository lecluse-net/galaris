"""Software-supplied definitions using the ordinary Service parameter contract."""

from typing import Any

from .contracts import FILE_INDEXING_PARAM, MANAGEMENT_SCOPE_PARAM, FileIndexingMode


def management_scope_parameter(scopes: tuple[str, ...], *, default: str = "usage") -> dict[str, Any]:
    """Opt a native Service into an explicitly delegated, connection-only scope."""
    if default not in scopes:
        raise ValueError("The default management scope must be an available scope")
    return {"type": "string", "required": False, "default": default,
            "label": "services.connectionParamLabels.managementScope",
            "description": "services.connectionParamDescriptions.managementScope",
            "options": [{"value": scope, "label": f"services.connectionParamOptions.managementScope.{scope}"}
                        for scope in scopes]}


def file_indexing_modes(code: str, config: dict[str, Any] | None, *, has_mail: bool = False) -> list[FileIndexingMode]:
    from app.file_share import available_bridges

    if has_mail and (not config or config.get("service") == "mail"):
        return ["excluded", "known_uris"]
    if not config or config.get("service") == "mail":
        return ["excluded"]
    if code == "console" and config.get("service") == "console":
        return ["excluded", "known_uris"]
    for bridge in available_bridges():
        if bridge.service == config.get("service"):
            return list(bridge.indexing_modes)
    return ["excluded"]


def with_standard_params(
    schema: dict[str, Any], *, code: str, file_share_config: dict[str, Any] | None,
    messenger_config: dict[str, Any] | None = None, has_mail: bool = False,
) -> dict[str, Any]:
    """Supply server-owned indexing and peer communication parameters."""
    params = dict(schema.get("params") or {})
    if messenger_config and messenger_config.get("service"):
        params[MANAGEMENT_SCOPE_PARAM] = {
            "type": "string", "required": False, "default": "team", "builtin": True,
            "label": "services.connectionParamLabels.peerCommunication",
            "description": "services.connectionParamDescriptions.peerCommunication",
            "options": [{"value": scope, "label": f"services.connectionParamOptions.peerCommunication.{scope}"}
                        for scope in ("none", "team", "all")],
        }
    elif params.get(MANAGEMENT_SCOPE_PARAM, {}).get("description") == "services.connectionParamDescriptions.peerCommunication":
        params.pop(MANAGEMENT_SCOPE_PARAM)
    modes = file_indexing_modes(code, file_share_config, has_mail=has_mail)
    if len(modes) > 1:
        params[FILE_INDEXING_PARAM] = {
            "type": "string", "required": False,
            "default": "known_uris" if "known_uris" in modes else "excluded", "builtin": True,
            "label": "services.connectionParamLabels.fileindexing",
            "description": "services.connectionParamDescriptions.fileindexing",
            "options": [{"value": mode, "label": f"services.connectionParamOptions.fileindexing.{mode}"}
                        for mode in modes],
        }
    else:
        params.pop(FILE_INDEXING_PARAM, None)
    return {**schema, "params": params}
