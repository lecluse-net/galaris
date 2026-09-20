"""Interpret internal checkpoint versions without exposing them to app.agent."""

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from app.agent.contracts import AgentRunCheckpoint, CheckpointAssessment


class InternalCheckpointPolicy:
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        data = checkpoint.data
        version = data.get("version")
        if type(version) is not int or version not in {1, 2, 3, 4}:
            return CheckpointAssessment(state="unsafe", reason="Unsupported internal checkpoint version.")
        raw = data.get("effects", [])
        if not isinstance(raw, list):
            return CheckpointAssessment(state="unsafe", reason="Invalid internal effect journal.")
        effects: list[Mapping[str, object]] = []
        for item in cast(list[object], raw):
            if not isinstance(item, Mapping):
                return CheckpointAssessment(state="unsafe", reason="Invalid internal effect record.")
            effect = cast(Mapping[str, object], item)
            if (effect.get("status") not in {"started", "outcome_unknown", "completed", "failed", "error_reported"}
                or effect.get("effect_policy", "non_idempotent") not in {"read", "idempotent", "non_idempotent"}):
                return CheckpointAssessment(state="unsafe", reason="Unknown effect state or safety policy.")
            if effect.get("status") == "error_reported":
                result = effect.get("result")
                reported: Mapping[str, object] = (
                    cast(Mapping[str, object], result) if isinstance(result, Mapping) else {}
                )
                if (version != 4 or effect.get("outcome") not in {"rejected", "unknown"}
                    or reported.get("schema") != "galaris.tool-error/v1"
                    or reported.get("status") != "error"
                    or reported.get("outcome") != effect.get("outcome")):
                    return CheckpointAssessment(state="unsafe", reason="Invalid reported tool error.")
            effects.append(effect)
        unresolved = [effect for effect in effects
            if effect.get("effect_policy", "non_idempotent") == "non_idempotent"
            and (effect.get("status") in {"started", "outcome_unknown"}
                 or (effect.get("status") == "failed" and effect.get("outcome") != "rejected"))]
        if unresolved:
            recoverable = (version in {3, 4} and data.get("resume_reconcilable") is True
                and all(effect.get("tool_name") in {"console_exec", "console_start"}
                    and effect.get("operation_id") and effect.get("recovery_scope")
                    for effect in unresolved))
            return CheckpointAssessment(
                state="reconcile" if recoverable else "unsafe",
                reason="Unacknowledged effects require reconciliation.",
            )
        return CheckpointAssessment(
            state="safe" if data.get("resume_safe") is True else "unsafe",
            reason="" if data.get("resume_safe") is True else "No effect safety marker.",
        )

    def rebase(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint | None:
        if not self.assess(checkpoint).resumable:
            return None
        return replace(checkpoint, result=None, data={**checkpoint.data, "message_history": []})


def create_policy() -> InternalCheckpointPolicy:
    return InternalCheckpointPolicy()
