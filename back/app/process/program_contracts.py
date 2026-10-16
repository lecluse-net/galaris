"""Optional documentary-program port, registered by its qualified owning module."""

from typing import Any, Protocol
from uuid import UUID


class ProgramExecutor(Protocol):
    async def execute(self, *, agent_id: int, program_uri: str, input_data: dict[str, Any],
                      invocation_key: UUID) -> dict[str, Any]: ...


_executor: ProgramExecutor | None = None


def register_program_executor(executor: ProgramExecutor) -> None:
    global _executor
    _executor = executor


def program_executor() -> ProgramExecutor | None:
    return _executor
