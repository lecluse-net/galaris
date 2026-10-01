"""Aggregate authorization telemetry with bounded labels and no action contents."""

import logfire

transitions = logfire.metric_counter("tool_authorization_transitions", unit="1")
wait_seconds = logfire.metric_histogram("tool_authorization_wait", unit="s")
delivery_failures = logfire.metric_counter("tool_authorization_delivery_failures", unit="1")
backlog = logfire.metric_gauge("tool_authorization_backlog", unit="1")


def transition(status: str, source: str) -> None:
    transitions.add(1, {"status": status, "source": source})
