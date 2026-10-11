"""Sequential, preemptible background maintenance."""

from .models import DreamReceipt
from .registry import register_mechanism
from .events import register_events

register_events()
from .scheduler import is_running, run_cycle, runtime_snapshot, start, stop

# Register provenance admission at bootstrap, even when Dream capture is disabled.
from app.memory.facade import register_source_evidence_access
from .evidence_access import conversation_evidence_clause, conversation_evidence_readable, conversation_evidence_readable_batch

register_source_evidence_access("conversation", conversation_evidence_clause, conversation_evidence_readable,
    batch_reader=conversation_evidence_readable_batch)

__all__ = [
    "DreamReceipt",
    "is_running",
    "register_mechanism",
    "run_cycle",
    "runtime_snapshot",
    "start",
    "stop",
]
