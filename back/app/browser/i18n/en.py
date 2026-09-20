"""English browser messages."""

default: dict[str, object] = {
    "browser": {
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
