"""Bounded Hermes file-exchange paths under the shared ``data/galaris`` root.

``AGENT_ROOT`` is the container view and ``BRIDGE_ROOT`` is the bridge API view of the
same location. No bridge file operation may escape this root.
"""

from app.file_share.path_normalization import normalize_file_reference

# Root directory under ``data``.
DIR_NAME = "galaris"

# Bridge-relative and agent-visible views of the same path.
BRIDGE_ROOT = f"data/{DIR_NAME}"
AGENT_ROOT = f"/opt/{BRIDGE_ROOT}"
RELATIVE_ALIASES = (BRIDGE_ROOT, DIR_NAME, AGENT_ROOT.lstrip("/"))


def to_runtime_path(path: str, *, allow_root: bool = False) -> str:
    """Normalize every supported Hermes spelling relative to its data root."""

    return normalize_file_reference(
        path,
        root=AGENT_ROOT,
        aliases=RELATIVE_ALIASES,
        allow_root=allow_root,
    )


def to_bridge_path(path: str) -> str:
    """Convert an agent-visible or relative path to the bridge API representation."""

    return f"{BRIDGE_ROOT}/{to_runtime_path(path)}"


def to_agent_path(bridge_path: str) -> str:
    """Convert a bridge-relative path into the agent-visible /opt path."""

    return f"{AGENT_ROOT}/{to_runtime_path(bridge_path)}"
