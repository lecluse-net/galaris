default = {
    "webhook": {
        "task": {
            "objective": "Process the ${source} webhook for ${agent_name}",
            "label": "Webhook ${source}",
            "created": "Task created successfully for the ${source} webhook",
        },
        "errors": {
            "invalid_payload": "The webhook payload must be UTF-8 text or a JSON object.",
            "body_too_large": "The webhook payload exceeds the 1 MiB limit.",
            "tool_name_required": "tool_name is required",
            "tool_not_found": "Tool '${tool_name}' not found",
            "listener_missing": "Tool '${tool_name}' has no listener configuration with connection_key",
            "required_field_missing": "Required field '${field}' is missing from the webhook data",
            "connection_not_found": "No active connection found for tool '${tool_name}' with ${key}=${value}",
            "connection_without_agent": "Connection found but no agent is associated",
        },
    }
}
