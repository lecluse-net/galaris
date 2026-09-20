"""English messages for tool discovery and search."""

default: dict[str, object] = {
    "tools": {
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
        "list_heading": "Your MCP tools, grouped by application tool:",
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
            "Tool '${name}' failed.\n"
            "Cause: ${reason}\n"
            "Technical type: ${error_type}.\n"
            "Next action: ${hint}\n"
            "Error reference: ${reference}"
        ),
        "call_failure_reasons": {
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
        "errors": {
            "system_read_only": "This mandatory system service is read-only and always enabled.",
            "tool_not_found": "Tool ${tool_id} not found",
            "tool_exists_code": "Tool '${code}' already exists",
            "invalid_yaml": "Invalid YAML",
            "invalid_tool_definition": "The tool definition is invalid",
            "password_default_forbidden": (
                "Password connection parameters cannot define a shared default: ${fields}"
            ),
            "secret_placeholder_without_value": (
                "The write-only value ${field} has no existing value to preserve"
            ),
            "yaml_mapping_required": "YAML must contain an object mapping",
            "code_missing": "Missing 'code' field",
            "tool_exists": "A tool named '${code}' already exists",
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
            "tool_configuration_error": "Tool '${code}': ${error}",
        },
    },
}
