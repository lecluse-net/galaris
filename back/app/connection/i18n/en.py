"""English connection API messages."""

default = {
    "connection_api": {
        "errors": {
            "not_found": "Connection not found",
            "not_found_by_id": "Connection ${connection_id} not found",
            "duplicate": "A connection already exists for agent ${agent_id} and tool ${tool_id}",
            "parameter_for_connection_not_found": "Parameter '${parameter}' was not found for connection ${connection_id}",
            "parameter_not_found": "Parameter '${parameter}' not found",
            "body_id_mismatch": "Body connection_id ${body_id} does not match URL ${url_id}",
            "tool_not_found": "Tool ${tool_id} not found",
            "tool_not_found_generic": "Tool not found",
            "no_mcp": "Tool ${tool_id} has no MCP configuration",
            "server_creation_failed": "Could not create the MCP server",
            "connection_error": "The external service could not be reached",
            "inactive": "Connection is inactive",
            "no_functions": "This connector does not expose functions",
        },
        "tools_available": "${count} tool(s) available",
    },
}
