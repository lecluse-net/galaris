"""Interpret internal checkpoint versions without exposing them to app.agent."""

from collections.abc import Mapping
from dataclasses import replace
from typing import cast

from app.agent.contracts import AIMessage, AgentRunCheckpoint, CheckpointAssessment

from .tool_results import decode_tool_result


AMENDMENT_RESUME_KEY = "amendment_resume"
RECORDED_TOOL_STATUSES = frozenset({"completed", "error_reported", "failed"})


class InternalCheckpointPolicy:
    def assess(self, checkpoint: AgentRunCheckpoint) -> CheckpointAssessment:
        data = checkpoint.data
        version = data.get("version")
        if type(version) is not int or version not in {1, 2, 3, 4, 5}:
            return CheckpointAssessment(state="unsafe", reason="Unsupported internal checkpoint version.")
        raw = data.get("effects", [])
        if not isinstance(raw, list):
            return CheckpointAssessment(state="unsafe", reason="Invalid internal effect journal.")
        effects: list[Mapping[str, object]] = []
        for item in cast(list[object], raw):
            if not isinstance(item, Mapping):
                return CheckpointAssessment(state="unsafe", reason="Invalid internal effect record.")
            effect = cast(Mapping[str, object], item)
            if (effect.get("status") not in {"started", "outcome_unknown", "completed", "failed", "error_reported", "interrupted", "waiting_for_authorization"}
                or effect.get("effect_policy", "non_idempotent") not in {"read", "idempotent", "non_idempotent"}):
                return CheckpointAssessment(state="unsafe", reason="Unknown effect state or safety policy.")
            # prepare_resume persists this state after closing a retryable call.
            # It is not evidence that an uncertain mutation can be replayed.
            if (effect.get("status") == "interrupted"
                and effect.get("effect_policy") not in {"read", "idempotent"}):
                return CheckpointAssessment(state="unsafe", reason="Interrupted effect is not replay-safe.")
            if effect.get("status") == "error_reported":
                result = effect.get("result")
                reported: Mapping[str, object] = (
                    cast(Mapping[str, object], result) if isinstance(result, Mapping) else {}
                )
                if (version not in {4, 5} or effect.get("outcome") not in {"rejected", "unknown"}
                    or reported.get("schema") != "galaris.tool-error/v1"
                    or reported.get("status") != "error"
                    or reported.get("outcome") != effect.get("outcome")):
                    return CheckpointAssessment(state="unsafe", reason="Invalid reported tool error.")
            effects.append(effect)
            if effect.get("status") == "waiting_for_authorization" and (
                version != 5 or effect.get("outcome") != "rejected" or not effect.get("authorization_request_id")
            ):
                return CheckpointAssessment(state="unsafe", reason="Invalid authorization waiting record.")
        unresolved = [effect for effect in effects
            if effect.get("effect_policy", "non_idempotent") == "non_idempotent"
            and (effect.get("status") in {"started", "outcome_unknown"}
                 or (effect.get("status") == "failed" and effect.get("outcome") != "rejected"))]
        if unresolved:
            recoverable = (version in {3, 4, 5} and data.get("resume_reconcilable") is True
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
        return replace(checkpoint, result=None, data={
            **checkpoint.data, "message_history": [], AMENDMENT_RESUME_KEY: True,
        })

    def prepare_retry(self, checkpoint: AgentRunCheckpoint) -> AgentRunCheckpoint:
        # Preserve the effect journal and history; only the failed attempt's result
        # is reset. Recovery still checks and reconciles uncertain effects.
        return replace(checkpoint, result=None, status="interrupted")

    def tool_history(self, checkpoint: AgentRunCheckpoint, *, limit: int) -> list[AIMessage]:
        effects = checkpoint.data.get("effects")
        if not isinstance(effects, list) or limit <= 0:
            return []
        history: list[AIMessage] = []
        entries = cast(list[object], effects)
        for index in range(len(entries) - 1, -1, -1):
            raw = entries[index]
            if not isinstance(raw, Mapping):
                continue
            effect = cast(Mapping[str, object], raw)
            status, name = effect.get("status"), effect.get("tool_name")
            if not isinstance(status, str) or status not in RECORDED_TOOL_STATUSES or not isinstance(name, str) or not name:
                continue
            arguments = effect.get("arguments")
            result = decode_tool_result(effect.get("result", effect.get("error")))
            call_id = effect.get("tool_call_id")
            history.append(AIMessage(
                type="tool", tool_name=name, content="", success=status == "completed",
                stream_id=f"{checkpoint.runtime_run_id}:{effect.get('id') or index}"[:500],
                tool_call_external_id=call_id[:500] if isinstance(call_id, str) else None,
                tool_arguments=cast(dict[str, object], arguments) if isinstance(arguments, dict) else None,
                tool_result=cast(dict[str, object], result) if isinstance(result, dict) else {"result": result},
            ))
            if len(history) == limit:
                break
        return list(reversed(history))


def create_policy() -> InternalCheckpointPolicy:
    return InternalCheckpointPolicy()
