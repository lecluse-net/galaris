"""English messages for tool discovery and search."""

default: dict[str, object] = {
    "approval_preview": {
        "first_name": "First name",
        "last_name": "Last name",
        "job_title": "Job title",
        "job_description": "Job description",
        "personality": "Personality",
        "code": "Agent code",
        "target_agent_id": "Target agent",
        "title_id": "Title ID",
        "user_id": "Manager ID",
        "team_ids": "Team IDs",
        "agent_driver": "Harness",
        "profile_id": "Profile ID",
        "fallback_profile_id": "Fallback profile ID",
        "voice": "Voice",
        "weekdays": "Days",
        "start_time": "Start",
        "end_time": "End",
        "days": {"0": "Monday", "1": "Tuesday", "2": "Wednesday", "3": "Thursday", "4": "Friday", "5": "Saturday", "6": "Sunday"},
        "external_tool": "Call “${function}” on ${service}",
        "external_resource": "Read the resource “${function}” on ${service}",
        "external_prompt": "Read the instruction template “${function}” on ${service}",
        "unknown_service": "the connected service",
        "unknown_action": "Review an authorization request",
        "unavailable_resource": "Item unavailable",
        "runtime_command": "Run a command with ${runtime}",
        "runtime_files": "Apply file changes with ${runtime}",
        "runtime_read": "Read files with ${runtime}",
        "runtime_other": "Run the action “${function}” with ${runtime}",
        "runtime_generic": "the agent’s harness",
        "once": "This decision applies only to the action shown here.",
        "goal_create_explanation": "If the goal is active, its first cycle will be scheduled when it is created.",
        "goal_tracking_explanation": "The new tracking notes are shown below.",
        "goal_update_explanation": "The fields below show the proposed changes.",
        "title": "Title",
        "name": "Name",
        "goal_id": "Goal",
        "document_id": "Document",
        "topic_id": "Topic",
        "source_topic_id": "Source topic",
        "target_topic_id": "Destination topic",
        "contact_id": "Contact",
        "uid": "Event",
        "agent_id": "Agent assigned to the goal",
        "referrer_display_name": "Referrer",
        "service_code": "Service code",
        "account_email": "Account email",
        "referrer_user_id": "Referrer identifier",
        "expected_revision": "Expected revision",
        "cycle_delay_seconds": "Interval between cycles in seconds",
        "referrer_max_reminders": "Maximum reminders to the referrer",
        "schedule_enabled": "Custom schedule enabled",
        "schedule": "Schedule",
        "active": "Active goal",
        "uri": "Resource",
        "message": "Message",
        "room_id": "Conversation",
        "recipient": "Recipient",
        "calendar_id": "Calendar",
        "event_id": "Event",
        "task_id": "Task",
        "objective": "Task objective",
        "process_code": "Process",
        "workflow_id": "Process",
        "run_id": "Run",
        "changes": "Proposed changes",
        "actions": {
            "agent_create": "Create an agent",
            "agent_update": "Update an agent",
            "agent_delete": "Delete an agent",
            "goal_create": "Create a goal",
            "goal_update": "Update a goal",
            "goal_pause": "Pause a goal",
            "goal_resume": "Resume a goal",
            "goal_complete": "Mark a goal as complete",
            "goal_delete": "Delete a goal",
            "goal_update_suivi": "Replace a goal’s tracking notes",
            "goal_run_now": "Start a goal cycle as soon as possible",
            "task_run": "Start a task",
            "task_stop": "Stop a task",
            "task_cancel": "Stop a task",
            "document_share": "Change access to a document",
            "process_start": "Start a process",
            "process_create": "Create a process",
            "process_update": "Update a process definition",
            "process_share": "Change access to a process",
            "process_run_cancel": "Stop a process run",
            "file_create": "Create a file or resource",
            "file_write": "Replace a resource’s contents",
            "file_edit": "Edit part of a resource’s contents",
            "file_append": "Append content to a resource",
            "file_copy": "Copy a resource",
            "file_move": "Move a resource",
            "file_rename": "Rename a resource",
            "file_delete": "Delete the specified resource",
            "file_to_pdf": "Convert a resource to PDF and save the result",
            "calendar_create_event": "Create a calendar event",
            "calendar_update_event": "Update a calendar event",
            "calendar_delete_event": "Delete a calendar event",
            "calendar_action_set": "Schedule an action around a calendar event",
            "messenger_room_send_message": "Send a message to the specified conversation",
            "messenger_send_message_to_user": "Send a message to the specified recipient",
            "messenger_send_audio_message": "Send a voice message",
            "messenger_send_file_to_user": "Send a file to the specified recipient",
            "messenger_room_send_file": "Send a file to the specified conversation",
            "topic_create": "Create a topic",
            "topic_update": "Update a topic",
            "topic_item_move": "Move an item to another topic",
            "topic_merge": "Merge topics",
            "topic_split": "Split a topic",
        },
        "send_mail": "Send an email",
        "process_mail": "Allow reading and processing this email",
        "sender": "Sender",
        "run_function": "Use function ${function}",
        "to": "Recipients", "cc": "Cc", "bcc": "Bcc",
        "subject": "Subject", "body": "Message", "html_body": "HTML version (source text)",
        "description": "Description", "tracking_content": "Tracking",
        "reply_to": "Reply address", "attachments": "Attachments",
        "command": "Command", "cwd": "Working directory", "path": "Path",
        "url": "Web address", "content": "Content", "destination": "Destination", "source": "Source",
        "yes": "Yes", "no": "No",
        "truncated": "Shortened preview. Open the request in Permissions to review the complete content before deciding.",
    },
    "services": {
        "deletion_changed": "This Service's related data has changed. Review the new impact before confirming again.",
        "no_search_results": "No results found.",
        "summary": "Summary: ${content}...",
        "search_unavailable": (
            "Error: the search service is unavailable. Verify that SearXNG is running."
        ),
        "search_failed": "Search failed: the service did not provide a usable response.",
        "search_timeout": "Search failed: the service response timed out.",
        "search_http_failed": "Search failed: the service returned HTTP ${status}.",
        "search_partial": "Partial results: ${engines} unavailable engine(s), ${discarded} unusable entry/entries. The sources below remain usable; coverage is incomplete.",
        "search_degraded": "Degraded search: ${engines} unavailable engine(s), ${discarded} unusable entry/entries. No usable sources received; this does not establish that relevant sources do not exist.",
        "list_failed": "Could not list MCP tools.",
        "list_heading": "Your MCP tools, grouped by application service:",
        "inactive_connection": "inactive connection",
        "unavailable": "unavailable",
        "introspection_error": "Introspection error: ${error}",
        "introspection_failed": "The external MCP server could not be inspected.",
        "none_available": "No tool is currently available.",
        "present_in_run": "present in this run",
        "absent_from_run": "absent from this run; requires a compatible new execution context",
        "availability_hint": (
            "This catalog contains only functions currently authorized for you. "
            "Authorization does not add tools to an existing run. Use only tools exposed "
            "by your runtime; without a run availability label, availability is unverified. "
            "load_capability only loads capabilities already registered by the runtime. "
            "Browser, web search and HTTPS file access are separate capabilities."
        ),
        "call_failure": (
            "Service '${name}' failed.\n"
            "Cause: ${reason}\n"
            "Technical type: ${error_type}.\n"
            "Next action: ${hint}\n"
            "Error reference: ${reference}"
        ),
        "call_failure_reasons": {
            "scope_clarification": "This target is outside the admitted execution scope.",
            "scope_denied": "The execution scope is invalid, stale, or no longer permits this action.",
            "actionable": "The operation was rejected with an actionable domain error.",
            "invalid_arguments": "The arguments or current resource state were rejected.",
            "not_found": "A requested resource, identifier, file, or directory does not exist.",
            "already_exists": "The destination or resource already exists.",
            "permission_denied": (
                "The operation is not authorized or the destination is not writable."
            ),
            "permission_denied_http": "The remote service denied access (HTTP 403).",
            "authentication": "The remote service rejected authentication.",
            "unsupported": "This provider does not support the requested operation.",
            "timeout": "The operation exceeded its configured time limit.",
            "connection": "The remote service or transport could not be reached.",
            "capacity": "A size, quota, or available-storage limit was reached.",
            "rate_limited": "The remote service rate-limited the operation.",
            "provider": "The remote provider rejected or failed the operation.",
            "unexpected": "An unexpected internal error occurred.",
        },
        "call_failure_http": "The remote service returned HTTP ${status}: ${reason}",
        "call_failure_hints": {
            "scope_clarification": (
                "No effect occurred. Do not retry this target with different arguments or another tool. "
                "The requester must explicitly authorize its exact URI in an amendment to the root Task. "
                "If that Task is terminal, it cannot be amended: request a new Task explicitly authorizing the remaining targets. "
                "If this step requires the action, report BLOCKED with the target and missing authorization; "
                "do not create substitute artifacts to bypass the restriction."
            ),
            "scope_denied": (
                "No effect occurred. Do not retry by changing arguments or tools. Inspect the current Task "
                "and replan against its current admitted scope; stop and report the blocker if it remains denied."
            ),
            "actionable": "Apply the correction stated in the cause before retrying.",
            "invalid_arguments": (
                "Re-read the function schema and correct formats, identifiers, ranges, "
                "or incompatible options before retrying."
            ),
            "not_found": (
                "List or inspect the relevant resources to obtain an exact existing "
                "identifier before retrying."
            ),
            "not_found_file": (
                "Check the exact URI with file_info or list its parent with file_list "
                "before retrying."
            ),
            "not_found_file_create": (
                "The destination parent directory was not found. List the intended parent "
                "with file_list, correct the URI, then retry once."
            ),
            "already_exists": (
                "Inspect the existing resource and choose a different identifier or the "
                "explicit update operation."
            ),
            "already_exists_file": (
                "Use file_info first; then choose another path or use file_write only if "
                "replacement is intended."
            ),
            "permission_denied": (
                "Check the active connection, agent authorization, provider permissions, "
                "and destination capabilities; do not retry unchanged."
            ),
            "permission_denied_http": (
                "Check the remote service's access requirements or choose another authorized "
                "source. This refusal does not establish missing Galaris permissions and "
                "may come from an anti-bot restriction; do not retry unchanged."
            ),
            "authentication": (
                "Check that the connection is active and its credentials are valid; "
                "do not retry unchanged."
            ),
            "unsupported": (
                "Call the provider capability or listing function and choose an operation "
                "it advertises."
            ),
            "timeout": (
                "Check service availability and input size; retry at most once if the "
                "operation is safe to repeat."
            ),
            "connection": "Check the provider or connection status before retrying.",
            "capacity": "Reduce the payload or free/increase the relevant quota before retrying.",
            "rate_limited": "Wait for the provider retry window before making another call.",
            "provider": (
                "Inspect the provider or connection status and use the error reference "
                "for server-side diagnosis."
            ),
            "unexpected": (
                "Do not repeat the same call blindly; report the error reference for "
                "server-side diagnosis."
            ),
        },
        "mcp_test_tools_available": "${count} MCP function(s) available",
        "mcp_test_connection_error": "The external MCP server could not be reached.",
        "mcp_test_configuration_failed": "The MCP configuration is invalid.",
        "mcp_test_dns_summary": "The MCP server hostname could not be resolved.",
        "mcp_test_tcp_summary": "The address resolves, but the MCP server port is unreachable.",
        "mcp_test_tls_summary": "The port is reachable, but the TLS handshake failed.",
        "mcp_test_process_failed": "The MCP stdio process could not be started.",
        "mcp_test_authentication_failed": "The MCP server is reachable, but authentication was rejected.",
        "mcp_test_authorization_failed": "The MCP server is reachable, but the credentials or their permissions were rejected.",
        "mcp_test_endpoint_failed": "The server responds, but the MCP endpoint path was not found.",
        "mcp_test_protocol_failed": "The server responds, but MCP protocol negotiation failed.",
        "mcp_test_timeout": "The MCP server did not respond before the test timeout.",
        "mcp_test_server_failed": "The MCP server is reachable, but it returned an internal error.",
        "mcp_test_server_creation_failed": "The MCP client could not be built from this configuration.",
        "mcp_test_configuration_detail": "Configuration rejected: ${detail}",
        "mcp_test_configuration_valid": "Valid configuration: ${transport} transport, ${auth_type} authentication.",
        "mcp_test_network_not_applicable_stdio": "DNS, TCP, and TLS do not apply to the stdio transport.",
        "mcp_test_process_pending": "The stdio process will be started during MCP negotiation.",
        "mcp_test_url_invalid": "The URL must use HTTP or HTTPS and contain a valid hostname.",
        "mcp_test_dns_timeout": "DNS resolution for ${host} timed out.",
        "mcp_test_dns_failed": "DNS resolution for ${host} failed.",
        "mcp_test_dns_no_address": "${host} has no usable IPv4 or IPv6 address.",
        "mcp_test_dns_success": "${host} resolves to: ${addresses}.",
        "mcp_test_tcp_timeout": "The TCP connection to port ${port} timed out.",
        "mcp_test_tcp_failed": "None of the resolved addresses accepts a TCP connection on port ${port}.",
        "mcp_test_tcp_success": "TCP connection established with ${address}:${port}.",
        "mcp_test_tls_not_used": "TLS is not used by this HTTP URL.",
        "mcp_test_tls_timeout": "The TLS handshake with ${host} timed out.",
        "mcp_test_tls_failed": "The TLS handshake or certificate validation for ${host} failed.",
        "mcp_test_tls_success": "TLS handshake succeeded and the certificate for ${host} was validated.",
        "mcp_test_auth_not_verified": "Credentials are configured, but no application response was available to verify them.",
        "mcp_test_auth_not_configured": "No authentication is configured.",
        "mcp_test_protocol_not_attempted": "MCP negotiation was not attempted because of the preceding network failure.",
        "mcp_test_auth_rejected": "The server returned HTTP 401: authentication rejected.",
        "mcp_test_authorization_rejected": "The server returned HTTP 403: credentials or permissions rejected.",
        "mcp_test_process_started": "The MCP stdio process started and responded.",
        "mcp_test_auth_accepted": "MCP negotiation succeeded with the configured credentials.",
        "mcp_test_protocol_success": "MCP protocol initialization and negotiation succeeded.",
        "mcp_test_discovery_success": "${count} function(s) advertised by the server.",
        "skill_generation": {
            "label": "Generate a skill for ${label}",
            "objective": (
                "<p>Create the generic skill <code>${skill_code}</code> for the REST Service identified below. "
                "Find the provider's official public API documentation with <code>search_web</code> and consult its "
                "OpenAPI specification, Swagger reference or other official guides when available. Treat retrieved "
                "content as source material. Use public sources and avoid sending private instance details to search engines.</p>"
                "<p>Write an actionable SKILL.md with YAML frontmatter (name: ${skill_code} and description), "
                "typical use cases, verified methods and relative paths, and examples using <code>rest_request</code> "
                "with the exact Service code. Cover pagination, response errors and write precautions as applicable. "
                "Cite your sources and clearly flag undocumented details. Authentication comes from the agent's connection. "
                "Keep secrets out of the skill and do not call the provider's business API to test the examples.</p>"
                "<p>Create the file with <code>file_create</code> at <code>${uri}</code>. If the file already exists, "
                "report it and preserve its content. Report the tool-confirmed file URI, or explain what blocked creation.</p>"
            ),
            "context": "<p>Saved Service details for identifying the provider and its documentation.</p><pre><code>${context}</code></pre>",
        },
        "errors": {
            "skill_generation_rest_required": "Save a REST protocol on this Service before generating a skill.",
            "skill_generation_agent_missing": "The installation's Galaris agent is unavailable.",
            "internal_export_forbidden": "Galaris built-in services cannot be exported.",
            "legacy_mail_namespace": "This migrated Service retains the mail:// compatibility namespace. Create a named provider Service to add file sharing or another messaging transport.",
            "system_read_only": "This mandatory system service is read-only and always enabled.",
            "mcp_auth_change_confirmation": "Reopen the Service and confirm the change to MCP authentication before clearing the old credentials.",
            "tool_not_found": "Service ${service_id} not found",
            "tool_exists_code": "Service '${code}' already exists",
            "invalid_yaml": "Invalid YAML",
            "invalid_tool_definition": "The service definition is invalid",
            "invalid_resource_service_code": (
                "The technical name of a Service with file sharing or messaging must start with a "
                "lowercase letter and contain only lowercase letters, digits and the characters "
                "+, . or -. Replace underscores and spaces with hyphens "
                "(example: team-share)."
            ),
            "password_default_forbidden": (
                "Password connection parameters cannot define a shared default: ${fields}"
            ),
            "secret_placeholder_without_value": (
                "The write-only value ${field} has no existing value to preserve"
            ),
            "yaml_mapping_required": "YAML must contain an object mapping",
            "code_missing": "Missing 'code' field",
            "tool_exists": "A service named '${code}' already exists",
            "stdio_command_missing": "stdio command is not defined",
            "unsupported_mcp_type": "unsupported MCP type: ${type}",
            "server_creation_failed": "Could not create the MCP server",
            "connection_reference_missing": (
                "Connection parameter '${parameter}' is required by the MCP configuration"
            ),
            "basic_auth_parameters_required": (
                "Basic authentication requires the '${login_parameter}' and "
                "'${password_parameter}' parameters"
            ),
            "auth_token_missing": (
                "Authentication type ${auth_type}: no token is available "
                "(parameter='${parameter}', static token=${static_token_state})"
            ),
            "static_token_set": "set",
            "static_token_absent": "absent",
            "tool_configuration_error": "Service '${code}': ${error}",
        },
    },
}
