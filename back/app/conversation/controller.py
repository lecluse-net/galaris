"""Registered controller port used by the conversation scheduler."""

from __future__ import annotations

from .contracts import ConversationController, ConversationOutcome, ConversationTurn


_controller: ConversationController | None = None


def register_controller(controller: ConversationController) -> None:
    """Register or replace the concrete controller at the composition boundary."""

    global _controller
    _controller = controller


async def run(turn: ConversationTurn) -> ConversationOutcome:
    if _controller is None:
        raise RuntimeError("No conversation controller is registered.")
    return await _controller.run(turn)


def reset_controller_for_tests() -> None:
    global _controller
    _controller = None


__all__ = ["register_controller", "run"]
