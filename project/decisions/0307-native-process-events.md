# 0307 — Durable events in native Processes

Status: accepted.

Process runs can wait for deadlines and externally observed events between activities.
The typed executable profile supports timer and correlated message catch events,
exclusive event-based gateways, and attached interrupting error events. BPMN export uses
the corresponding model elements.

The occurrence stores armed waits, absolute deadlines and the winning receipt. Event
acceptance and deduplication use the existing run lock and journal. A producer addresses
the run, event name and correlation value explicitly. A producer handling mail, files,
or other events can use the same Process contract. Its own routing and delivery policy
belong to the producer.

An error boundary may handle a qualified, confirmed activity failure. Unknown operation
outcomes keep the existing reconciliation path. A caught failure keeps its occurrence
and effect receipt in the execution history.
