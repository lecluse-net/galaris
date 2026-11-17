"""English browser messages."""

default: dict[str, object] = {
    "browser": {
        "permission_question": "Allow this agent’s browser to ${action} on ${origin}? The decision is remembered for this request type and covers all paths at this destination.",
        "permission_local_question": "Allow this agent’s browser to access ${origin} on the local network? The decision covers all paths at this destination for this agent.",
        "permission_actions": {
            "get": "read data (GET)",
            "head": "check a resource’s metadata (HEAD)",
            "options": "check supported operations (OPTIONS)",
            "post": "send data (POST)",
            "put": "create or replace a resource (PUT)",
            "patch": "modify part of a resource (PATCH)",
            "delete": "request deletion of a resource (DELETE)",
            "websocket": "open a WebSocket connection",
        },
        "all_sites_permission_question": "Always allow this agent's browser to access all websites without further site permission requests? This covers all domains, protocols, ports, paths, configured HTTP methods and WebSocket. Network filters, explicit refusals and separate local-network permissions still apply. Revoke this agreement in Remembered permissions.",
        "errors": {
            "invalid_url": "The URL is invalid. Use an HTTP(S) URL without embedded credentials.",
            "invalid_viewport": (
                "The viewport must be 320–3840 CSS pixels wide and "
                "240–2160 CSS pixels high."
            ),
            "session_not_found": "This browser session is unavailable or no longer belongs to this task.",
            "capacity_reached": "The browser is at capacity. Close an existing session or retry shortly.",
            "unavailable": "The isolated browser service is unavailable.",
            "failed": "The browser operation failed (${code}).",
        },
        "closed": "Browser session ${session_id} closed.",
    }
}
