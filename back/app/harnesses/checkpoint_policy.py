"""A remote checkpoint addresses the existing runtime actor; it never restarts work."""

from app.agent import AgentRunCheckpoint
from app.agent.contracts import CheckpointAssessment


class RuntimeCheckpointPolicy:
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        valid = checkpoint.data.get("version") == 1 and bool(checkpoint.data.get("run_context"))
        valid = valid and len(checkpoint.runtime_run_id) == 64 and checkpoint.status in ("running", "waiting_for_authorization")
        return CheckpointAssessment(state="safe" if valid else "unsafe",
            reason="" if valid else "There is no live managed runtime continuation")

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None:
        # Changing the objective requires stopping and observing the previous actor first.
        return None


def create_policy() -> RuntimeCheckpointPolicy:
    return RuntimeCheckpointPolicy()
