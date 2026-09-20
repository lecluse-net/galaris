"""Registration port for Tool-specific file transports owned by bridges."""

from collections.abc import Callable

from .transport import FileTransport

ResourceTransportFactory = Callable[[int], FileTransport]
_resource_transports: dict[str, ResourceTransportFactory] = {}


def register_resource_transport(tool_code: str, factory: ResourceTransportFactory) -> None:
    _resource_transports[tool_code] = factory


def connected_resource_transport(tool_code: str, agent_id: int) -> FileTransport | None:
    """Call only after the caller has verified this agent's active connection."""
    factory = _resource_transports.get(tool_code)
    return factory(agent_id) if factory else None


def resource_transport_factory(tool_code: str) -> ResourceTransportFactory | None:
    return _resource_transports.get(tool_code)
