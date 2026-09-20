"""English Hermes bridge messages."""

default = {
    "hermes": {
        "tool_completed": "Completed.",
        "tool_running": "Running...",
        "kanban_completed_without_summary": (
            "Hermes completed the Kanban task without a handoff summary."
        ),
        "approval_default_description": "potentially dangerous command",
        "approval_reason": "Reason",
        "approval_command": "Command",
        "approval_title": "Approval required",
        "approval_once": "Approve once",
        "approval_session": "Approve for this session",
        "approval_deny": "Deny",
        "approval_auto_granted": "Approval granted automatically (auto_approve).",
        "approval_auto_failed": "Automatic Hermes approval failed.",
        "approval_agent_denied": "Approval denied because the requester is an agent, not a human. Enable auto_approve to allow it.",
        "approval_request_sent": "Approval request sent to the conversation.",
        "approval_no_channel": "Hermes approval denied automatically because no messenger channel is available.",
        "errors": {
            "agent_not_found": "Agent not found.",
            "wrong_driver": "This agent does not use the Hermes driver.",
            "no_runtime": "This agent has no Hermes runtime.",
            "mcp_url_required": "APP_HOST is required for the Hermes LLM proxy",
            "agent_code_missing": "Agent ${agent_id} has no configured code.",
            "model_missing": "No effective model is configured for Hermes agent ${agent_code}",
            "system_token_missing": "Hermes system token is missing for agent ${agent_code}",
            "template_missing": "default-agent directory not found: ${path}",
            "configuration_incomplete": (
                "Agent ${agent_code} has incomplete Hermes configuration "
                "(url, api_key, model)."
            ),
            "connect_failed": "Failed to connect to Hermes: ${error}",
            "run_events_http": "Hermes run events returned HTTP ${status}: ${error}",
            "run_id_missing": "Hermes /v1/runs returned no run_id",
            "run_not_found": "Hermes no longer knows run ${run_id}; it cannot be resumed.",
            "run_ended": "Hermes run ended with status ${status}.",
            "execution_failed": "Error: ${error}",
            "session_create_failed": (
                "Error: unable to create Hermes session '${session_id}' (${error}). "
                "The instance may not support /api/sessions and may require an update."
            ),
            "run_start_failed": "Error: unable to start the Hermes run (${error}).",
            "generic": "Hermes error",
            "llm_interrupted": "LLM call interrupted with status ${status}.",
            "terminal_result_missing": "The Hermes driver produced no terminal result.",
            "kanban_transport_invalid": (
                "Unsupported Hermes Kanban transport: ${transport}."
            ),
            "kanban_task_id_invalid": "Invalid Hermes Kanban task id.",
            "kanban_board_unsupported": (
                "Unsupported Hermes Kanban board: ${board}."
            ),
            "kanban_configuration_incomplete": (
                "The Hermes Kanban execution configuration is incomplete."
            ),
            "kanban_management_unsupported": (
                "The generic harness manager does not expose Hermes Kanban commands. "
                "New Hermes runs use the direct streaming API instead."
            ),
            "kanban_terminal_failure": (
                "Hermes Kanban ended with status ${status}: ${reason}"
            ),
            "path_empty": "Path is empty.",
            "path_traversal": "Path traversal is forbidden: ${path}",
            "path_invalid": "Invalid path: ${path}",
            "path_outside_root": "Access outside ${root} is forbidden: ${path}",
            "filename_missing": "Missing file name below ${root}: ${path}",
            "cancel_run_not_active": (
                "No active Hermes runtime run is registered for ${run_id}."
            ),
        },
    }
}
