"""Software-supplied definitions using the ordinary Tool parameter contract."""

from typing import Any

from .contracts import FILE_INDEXING_PARAM, MANAGEMENT_SCOPE_PARAM, FileIndexingMode


def management_scope_parameter(scopes: tuple[str, ...]) -> dict[str, Any]:
    """Opt a native Tool into an explicitly delegated, connection-only scope."""
    return {"type": "string", "required": False, "default": "usage",
            "label": "tools.connectionParamLabels.managementScope",
            "description": "tools.connectionParamDescriptions.managementScope",
            "options": [{"value": scope, "label": f"tools.connectionParamOptions.managementScope.{scope}"}
                        for scope in scopes]}


def file_indexing_modes(code: str, config: dict[str, Any] | None) -> list[FileIndexingMode]:
    from app.file_share import available_bridges

    if not config or code == "mail" or config.get("service") == "mail":
        return ["excluded"]
    if code == "console" and config.get("service") == "console":
        return ["excluded", "known_uris"]
    for bridge in available_bridges():
        if bridge.service == config.get("service"):
            return list(bridge.indexing_modes)
    return ["excluded"]


def with_standard_params(
    schema: dict[str, Any], *, code: str, file_share_config: dict[str, Any] | None,
    messenger_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Supply server-owned indexing and peer communication parameters."""
    params = dict(schema.get("params") or {})
    if messenger_config and messenger_config.get("service"):
        params[MANAGEMENT_SCOPE_PARAM] = {
            "type": "string", "required": False, "default": "team", "builtin": True,
            "label": "tools.connectionParamLabels.peerCommunication",
            "description": "tools.connectionParamDescriptions.peerCommunication",
            "options": [{"value": scope, "label": f"tools.connectionParamOptions.peerCommunication.{scope}"}
                        for scope in ("none", "team", "all")],
        }
    elif params.get(MANAGEMENT_SCOPE_PARAM, {}).get("description") == "tools.connectionParamDescriptions.peerCommunication":
        params.pop(MANAGEMENT_SCOPE_PARAM)
    modes = file_indexing_modes(code, file_share_config)
    if len(modes) > 1:
        params[FILE_INDEXING_PARAM] = {
            "type": "string", "required": False,
            "default": "known_uris" if "known_uris" in modes else "excluded", "builtin": True,
            "label": "tools.connectionParamLabels.fileindexing",
            "description": "tools.connectionParamDescriptions.fileindexing",
            "options": [{"value": mode, "label": f"tools.connectionParamOptions.fileindexing.{mode}"}
                        for mode in modes],
        }
    else:
        params.pop(FILE_INDEXING_PARAM, None)
    return {**schema, "params": params}
