"""English browser messages."""

default: dict[str, object] = {
    "browser": {
        "permission_question": "Allow this agent's browser to perform ${action} access to ${origin}? This decision covers all paths on this origin and will be remembered for this agent.",
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
