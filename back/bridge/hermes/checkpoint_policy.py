"""Recovery of Hermes runs observes their remote identity instead of replaying effects."""

from app.agent.contracts import AgentRunCheckpoint, CheckpointAssessment


class HermesCheckpointPolicy:
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        strategy = str(checkpoint.data.get("execution_strategy") or "direct")
        if strategy not in {"direct", "kanban"}:
            return CheckpointAssessment(state="unsafe", reason="Unknown Hermes checkpoint strategy.")
        if not checkpoint.runtime_run_id.strip():
            return CheckpointAssessment(state="unsafe", reason="Missing Hermes run identity.")
        if checkpoint.runtime_run_id.startswith("pending:") and (
            strategy != "kanban" or not checkpoint.data.get("idempotency_key")
        ):
            return CheckpointAssessment(state="unsafe", reason="Missing remote admission idempotency key.")
        return CheckpointAssessment(
            state="reconcile", execution_strategy=strategy,
            reason="Observe the existing remote run; do not replay its effects.",
        )

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None:
        # Hermes owns an opaque, possibly still executing remote history. An amendment
        # cannot safely erase it or start another run from this local checkpoint.
        return None


def create_policy() -> HermesCheckpointPolicy:
    return HermesCheckpointPolicy()
