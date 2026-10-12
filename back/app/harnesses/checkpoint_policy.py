"""A remote checkpoint addresses the existing runtime actor; it never restarts work."""

from app.agent import AgentRunCheckpoint
from app.agent.contracts import CheckpointAssessment


class RuntimeCheckpointPolicy:
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        valid = type(checkpoint.data.get("version")) is int and checkpoint.data.get("version") == 1
        valid = valid and bool(checkpoint.data.get("run_context")) and len(checkpoint.runtime_run_id) == 64
        if not valid:
            return CheckpointAssessment(state="unsafe", reason="The managed runtime checkpoint identity is incomplete or unsupported.")
        if checkpoint.status == "interrupted":
            # Older Task retries overwrote this local status. Observe the existing
            # actor with the original authority; never submit another run.
            return CheckpointAssessment(state="reconcile", reason="Observe the interrupted managed runtime; do not restart it.")
        if checkpoint.status not in ("running", "waiting_for_authorization"):
            return CheckpointAssessment(state="unsafe", reason="The managed runtime has no resumable state.")
        return CheckpointAssessment(state="safe")

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None:
        # Changing the objective requires stopping and observing the previous actor first.
        return None


def create_policy() -> RuntimeCheckpointPolicy:
    return RuntimeCheckpointPolicy()
