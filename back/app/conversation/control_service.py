"""Durable human commands, applied between conversation tool effects."""

from .contracts import ConversationControlAction
from .models import ConversationRound

REQUESTED_ACTIONS = ("pause", "stop", "respond")


def available_round_actions(round_: ConversationRound) -> list[ConversationControlAction]:
    if round_.voice_session_id is not None or round_.delivery_state in {"SENDING", "UNKNOWN", "DELIVERED"}:
        return []
    if round_.control_action in REQUESTED_ACTIONS:
        return ["stop"] if round_.control_action != "stop" else []
    if round_.status in {"FROZEN", "CLAIMED", "RUNNING", "WAITING_APPROVAL"}:
        if round_.response_only:
            return ["pause", "stop"]
        return ["pause", "stop", "respond"]
    if round_.status == "PAUSED":
        return ["resume", "stop", "respond"]
    if round_.status == "CANCELLED" and round_.resolved_by_round_id is None:
        return ["restart"]
    return []
