"""Software-supplied definitions using the ordinary Tool parameter contract."""

from typing import Any

from .contracts import FILE_INDEXING_PARAM, FileIndexingMode


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
) -> dict[str, Any]:
    """Supply provider-bounded indexing choices without changing custom definitions."""
    params = dict(schema.get("params") or {})
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
