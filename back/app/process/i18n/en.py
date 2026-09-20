default = {
    "process": {
        "tracking": "Process started. Galaris tracking ID: ${run_id}.",
        "summary": {
            "queued": "The process is queued.",
            "running": "The process is running.",
            "waiting": "The process is waiting for an external or human event.",
            "success": "The process completed successfully.",
            "error": "The process completed with an error.",
            "cancelling": "The process is being cancelled.",
            "cancelled": "The process was cancelled.",
            "unknown": "The process status could not be determined.",
        },
        "await_label": "Waiting for process ${label}",
        "await_objective": "Wait for process ${label} (${run_id}) to complete.",
        "await_success": "Process ${label} finished with status ${status}. Result: ${output}",
        "await_error": "Process ${label} finished with status ${status}. Error: ${error}",
        "await_timeout": "The wait for process ${label} timed out. The run is still active and can be tracked with ID ${run_id}.",
        "recommendation_retry": "Check the configuration and input data before retrying.",
        "recommendation_engine": "Check the process engine availability and credentials.",
        "fake_engine_available": "Fake process engine available.",
        "n8n": {
            "invalid_api_response": "This address did not return an n8n API list response.",
            "api_key_missing": "The n8n API key is not configured.",
            "api_url_missing": "The n8n API URL is not configured.",
            "cancel_api_unavailable": (
                "This n8n instance does not expose execution cancellation through its public API."
            ),
            "invalid_webhook_url": "Invalid n8n webhook URL.",
            "workflow_webhook_missing": "The workflow configures no n8n webhook.",
            "webhook_execution_id_missing": (
                "The n8n webhook returned no execution ID (executionId, execution_id, or id)."
            ),
            "execution_id_unknown": "The n8n execution ID is unknown.",
            "api_available": "n8n API available; discovered ${count} workflow(s).",
            "execution_error": "n8n execution error",
        },
        "errors": {
            "not_allowed": "Process ${process_code} is not allowed for this agent.",
            "run_not_visible": "The requested run was not found or isn't visible to this agent.",
            "start_failed": "Process ${process_code} could not be started: ${reason}",
            "resource_not_found": "Resource not found",
            "process_not_found": "Process not found",
            "run_not_found": "Run not found.",
            "file_not_found": "File not found",
            "agent_not_found": "Agent not found.",
            "tool_not_found": "Process tool not found.",
            "already_linked": "This engine process is already linked to Galaris.",
            "workflow_without_agent": "Galaris workflow not found or has no associated agent.",
            "wrong_workflow": "The run does not belong to the specified workflow.",
            "resource_uri_invalid": "Invalid file resource URI: ${uri}",
            "resource_too_large": "File ${uri} exceeds the ${max_bytes}-byte process limit.",
            "active_run_delete": "An active run must finish or be cancelled before deletion.",
            "invalid_callback_token": "Invalid callback token.",
            "retry_terminal_only": "Only failed or cancelled runs can be retried.",
            "definition_not_found": "Process definition not found.",
            "correlation_not_found": "Correlation run not found.",
            "correlated_process_denied": "This agent is not allowed to use the correlated process.",
            "invalid_file_token": "Invalid file token.",
            "file_reference_expired": "The file reference has expired.",
            "file_wrong_run": "This file does not belong to the run.",
            "engine_code_required": "A process engine must have a code.",
            "engine_not_configured": "Process engine is not configured: ${code}",
            "workflow_not_allowed": (
                "Workflow is not allowed for this agent: ${workflow_id}"
            ),
            "engine_process_id_missing": (
                "The definition has no engine process ID."
            ),
            "engine_rejected": "The process engine rejected the run.",
            "engine_timeout": "Process engine connection timed out.",
        },
    }
}
