"""Dataset contributions are composed after module imports."""

from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .usage import UsageSource


def register_dataset_usage_source(kind: str, name: str, source: UsageSource) -> None:
    from .usage import register_dataset_usage_source as register
    register(kind, name, source)

def register_dataset() -> None:
    from app.file_share import register_native_provider, register_resource_aliases
    from app.memory import register_dataset_compatibility, refresh_dataset_projection
    from .compatibility import LegacyDatasetAdapter
    from .projection import register_projection_writer
    from .provider import DatasetProvider, resolve_alias

    register_native_provider("data", DatasetProvider())
    register_resource_aliases("dataset", resolve_alias)
    register_dataset_compatibility(LegacyDatasetAdapter())
    register_projection_writer(refresh_dataset_projection)
