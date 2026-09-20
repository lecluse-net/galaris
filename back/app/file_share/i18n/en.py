"""English file-sharing messages exposed to agents."""

default: dict[str, object] = {
    "file_share": {
        "operations": {
            "sign_in": "sign-in",
            "upload": "upload",
            "download": "download",
            "webdav_upload": "WebDAV upload",
            "webdav_download": "WebDAV download",
            "share_creation": "share creation",
        },
        "upload_failed": "Upload through ${tool_code} failed: ${error}",
        "affine_upload_path": (
            "AFFiNE upload failed: put the workspace at the start of destination "
            "(for example, company/my_file)."
        ),
        "upload_ok": "File uploaded through ${tool_code} (${service}, ${size} bytes): ${location}",
        "download_failed": "Download through ${tool_code} failed: ${error}",
        "affine_download_path": (
            "AFFiNE download failed: put the workspace at the start of remote "
            "(for example, company/<key>)."
        ),
        "download_ok": "File downloaded through ${tool_code} (${service}, ${size} bytes): ${location}",
        "destination_required": "Transfer failed: dest_path is required.",
        "transfer_ok": (
            "File transferred ${source} -> ${destination} (${size} bytes): ${location}"
        ),
        "transfer_failed": "Transfer ${source} -> ${destination} failed: ${error}",
        "targets_failed": "Could not list file-sharing services: ${error}",
        "no_targets": (
            "No file-sharing service is connected to your account. Ask an administrator to "
            "enable a file-sharing connection."
        ),
        "targets_heading": "Connected file-sharing services (value for tool_code):",
        "messenger_label": "Your messaging service",
        "messenger_description": "Internal transport: exchange files through your messaging service.",
        "errors": {
            "required_parameter": (
                "Service '${service}': required parameter '${parameter}' was not provided "
                "(mapped connection parameter: '${connection_parameter}')."
            ),
            "connection_not_found": (
                "No active 'file_share/${tool_code}' connection is configured for agent "
                "${agent_id}."
            ),
            "service_connection_not_found": (
                "No active 'file_share/${service}' connection is configured for agent "
                "${agent_id}."
            ),
            "messenger_not_configured": (
                "No messaging service is configured for agent ${agent_id}."
            ),
            "nextcloud_only": "Sharing is supported by Nextcloud only.",
            "unknown_bridge": (
                "Unknown file-sharing bridge: '${service}'. Available: ${available}."
            ),
            "messaging_target_required": (
                "Messaging target is missing; provide a room_id or u:<user_id> for a direct "
                "message."
            ),
            "room_required": "A room_id is required to locate a messaging attachment.",
            "attachment_not_found": (
                "Attachment '${attachment}' was not found in recent messages from room "
                "${room_id}."
            ),
            "operation_failed": (
                "${service} ${operation} failed (status=${status}): ${detail}"
            ),
            "folder_creation_failed": (
                "Nextcloud folder creation failed for '${path}' (status=${status}): ${detail}"
            ),
            "affine_workspace_required": (
                "AFFiNE workspace is missing; put it at the start of the path "
                "(for example 'company/my_file')."
            ),
            "affine_session_cookie_missing": (
                "AFFiNE sign-in returned no session cookie. Check the email, password, and "
                "sign-in endpoint."
            ),
            "affine_graphql_failed": "AFFiNE GraphQL upload failed: ${error}",
            "affine_blob_key_missing": (
                "AFFiNE upload response contains no blob key."
            ),
            "grav_target_required": (
                "Grav upload has no target page. Use destination='page/file.ext' or configure "
                "the optional default_page parameter."
            ),
        },
    },
}
