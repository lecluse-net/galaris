"""Human-directory port shared with Goals at the application composition root."""

from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ProcessHumanContact:
    user_id: int | None
    display_name: str
    connection_id: int | None = None
    external_user: str | None = None


class ProcessHumanDirectory(Protocol):
    async def list_humans(self, *, agent_id: int) -> tuple[ProcessHumanContact, ...]: ...


@dataclass(frozen=True, slots=True)
class ProcessHumanRequest:
    attempt_id: UUID
    run_id: UUID
    agent_id: int
    user_id: int
    title: str
    instructions: str
    input: dict[str, Any]
    outputs: list[dict[str, Any]] | None
    files: list[dict[str, Any]]
    decision: bool = False
    question_id: UUID | None = None


class ProcessHumanMessenger(Protocol):
    async def requester(self, run_id: UUID, agent_id: int) -> int | None: ...
    async def deliver(self, request: ProcessHumanRequest, contact: ProcessHumanContact | None) -> None: ...
    async def withdraw(self, *, agent_id: int, attempt_id: UUID, question_id: UUID | None = None) -> None: ...


_messenger: ProcessHumanMessenger | None = None


async def process_requester(run_id: UUID, agent_id: int) -> int | None:
    return await _messenger.requester(run_id, agent_id) if _messenger is not None else None


def register_process_human_messenger(messenger: ProcessHumanMessenger) -> None:
    global _messenger
    _messenger = messenger


async def deliver_process_human_request(request: ProcessHumanRequest) -> None:
    if _messenger is None:
        raise RuntimeError("The process messaging port is not configured")
    contacts = await list_process_humans(request.agent_id)
    contact = next((item for item in contacts if item.user_id == request.user_id), None)
    await _messenger.deliver(request, contact)


async def withdraw_process_human_request(*, agent_id: int, attempt_id: UUID,
                                         question_id: UUID | None = None) -> None:
    if _messenger is None:
        raise RuntimeError("The process messaging port is not configured")
    await _messenger.withdraw(agent_id=agent_id, attempt_id=attempt_id, question_id=question_id)


_directory: ProcessHumanDirectory | None = None


def register_process_human_directory(directory: ProcessHumanDirectory) -> None:
    global _directory
    _directory = directory


async def list_process_humans(agent_id: int) -> tuple[ProcessHumanContact, ...]:
    if _directory is None:
        raise RuntimeError("The process human directory is not configured")
    return await _directory.list_humans(agent_id=agent_id)
