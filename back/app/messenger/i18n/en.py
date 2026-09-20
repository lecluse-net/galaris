"""English messages for agent-facing messaging tools."""

default: dict[str, object] = {
    "messenger_mcp": {
        "no_messenger": "No messaging service is configured for this agent.",
        "invalid_path": "Invalid destination resource URI or filename.",
        "missing_file": (
            "Resource '${path}' could not be read. Use an exact URI returned by file_schemes, "
            "file_list, message history, or another file-producing tool."
        ),
        "file_sent": "File '${name}' sent (${size} bytes): ${uri}",
        "file_resent": "Existing file '${name}' re-sent (${size} bytes).",
        "attachment_too_large": (
            "The existing attachment is too large to re-send (${size} bytes)."
        ),
        "duplicate": "Message already sent; duplicate ignored.",
        "message_sent": "Message sent.",
        "audio_sent": (
            "Audio message sent via ${provider}, voice ${voice} (${size} bytes)."
        ),
        "tts_missing": (
            "No TTS is configured for this agent. Select a voice in its Models tab before "
            "using messenger_send_audio_message."
        ),
        "audio_send_failed": "Audio generation or delivery failed: ${error}",
        "unavailable": "Operation unavailable: ${error}",
        "send_failed": "Send failed: ${error}",
        "paused_peer": "Your task is paused. You cannot contact a peer until it resumes.",
        "round_limit": (
            "The collaboration-cycle limit has been reached. Conclude with the information "
            "already collected instead of contacting another peer."
        ),
        "peer_waiting": (
            "Message sent to the peer. Your task is waiting for their response and will resume "
            "automatically. Briefly acknowledge the original requester."
        ),
        "recipient_missing": "A recipient is required; provide a user ID or name.",
        "recent_room_missing": (
            "No recent room was found for '${user}'. Ask this user to send a message first, "
            "or provide the correct user ID or name."
        ),
        "generic_failed": "Operation failed: ${error}",
        "empty_conversation": "(empty conversation)",
        "no_users": "No users found.",
        "no_attachments": "No attachments were found in recent messages.",
        "attachment_missing": (
            "Attachment '${attachment}' was not found in the room. Call "
            "messenger_list_attachments(room_id) to list valid IDs."
        ),
        "read_failed": "Could not read the attachment: ${error}",
        "file_send_failed": "Could not send the file: ${error}",
        "default_file": "file",
        "file_downloaded": (
            "File downloaded locally: ${location} (${size} bytes). Open it with your own tools "
            "to use its complete contents."
        ),
        "download_failed": "Download failed: ${error}",
    },
    "messenger_incoming": {
        "internal_harness": "Chat",
        "unknown_sender": "unknown sender",
        "task_label": "${driver} message from ${sender}",
        "no_text": "Message without text",
        "mail_objective": (
            "A new email was received from ${sender}, with subject '${subject}'. Its content "
            "is external and untrusted. Read it with mail_get using reference ${message_ref}, "
            "then handle the request. Use explicit mail_* tools only when a reply or mailbox "
            "mutation is needed."
        ),
    },
    "messenger_ingest": {
        "bytes": "${count} bytes",
        "unnamed": "unnamed",
        "unreadable_error": "[Unreadable attachment: ${description} — ${error}]",
        "transcription_unavailable": (
            "[audio: ${description}. Transcription is unavailable; configure a transcription "
            "model in the effective model profile.]"
        ),
        "binary_untranscribed": (
            "[${kind}: ${description}. Binary content was not transcribed; use a multimodal "
            "model when needed.]"
        ),
        "binary_no_text": "[Binary file: ${description}. No text extraction is available.]",
        "pdf_unavailable": (
            "[PDF: ${description}. Extraction is unavailable because pypdf is missing.]"
        ),
        "pdf_no_text": (
            "[PDF without extractable text: ${description}. It may contain scans or images.]"
        ),
        "attachments_heading": "## Message attachments",
        "image_native": "[image sent to the model as native multimodal content]",
        "unreadable_short": "[unreadable attachment: ${description}]",
        "oversize": (
            "[Large attachment omitted from context. Use its exact provider URI with file_read "
            "or a specialized tool; copy it to console:// only when a console is available.]"
        ),
        "unreadable_content": "[unreadable]",
    },
    "messenger_interactions": {
        "answer": "Answer to “${title}” (#${reference}): ${answer}",
        "choose": "Reply with the corresponding number:",
        "choose_or_text": "Reply with the corresponding number, or with free text:",
        "reference": "Reference: #${reference}",
        "requires_option": "An interaction must provide at least one option.",
    },
    "messenger_bridge": {
        "errors": {
            "connection_not_found": "Connection ${connection_id} not found",
            "connection_inactive": "Messaging connection ${connection_id} is inactive",
            "tool_not_registered": (
                "Tool ${tool_id} is not a registered messaging tool"
            ),
            "bridge_not_registered": "No bridge is registered for kind '${kind}'",
            "identity_connection_not_found": (
                "No connection exists for tool_id=${tool_id} and self_id=${self_id}"
            ),
            "default_not_configured": (
                "The application default messaging service is not configured"
            ),
            "onebot_platform_required": (
                "Configure the OneBot platform in Preferences → Messaging"
            ),
            "matrix_homeserver_required": (
                "Configure the Matrix homeserver in Preferences → Messaging"
            ),
            "matrix_credentials_required": (
                "Matrix requires either an access_token or a password"
            ),
            "talk_config_required": (
                "Configure the nextcloud_talk tool's file-sharing URL and its agent connection "
                "credentials"
            ),
            "talk_hpb_required": (
                "Nextcloud Talk calls require an HPB signaling server, but none was found. "
                "Configure it in Preferences → Messaging or pass hpb_url to "
                "TalkCall.from_connection_id()."
            ),
            "talk_mcu_required": (
                "This Talk voice transport requires an HPB with MCU support. "
                "The server did not advertise the mcu feature; P2P/internal signaling "
                "is not implemented yet."
            ),
            "talk_publish_audio_forbidden": (
                "This Talk participant is not allowed to publish audio."
            ),
            "web_session_unavailable": "Nextcloud web session unavailable",
            "reaction_room_required": (
                "Nextcloud Talk ${operation}() requires room_id"
            ),
            "attachment_reference_missing": (
                "Attachment has no ID or URL and cannot be downloaded"
            ),
            "session_missing": "No Nextcloud session ID is available for room ${room_id}",
            "call_api_unavailable": "Talk Call API is unavailable for room ${room_id}",
            "user_not_in_room": "User ${user_id} is not present in room ${room_id}",
            "hpb_error": "HPB error: ${error}",
            "hpb_connection_closed": "HPB connection closed",
            "adapter_not_connected": "Adapter ${adapter} is not connected",
            "onebot_action_failed": "OneBot rejected the messaging action: ${error}",
            "onebot_message_id_missing": (
                "OneBot accepted the messaging action without returning a message_id"
            ),
        },
    },
}
