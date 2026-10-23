"""Dataset contributions are composed after module imports."""

from __future__ import annotations
from typing import TYPE_CHECKING
from uuid import UUID
if TYPE_CHECKING:
    from .usage import UsageSource
    from .contracts import DataActor
    from app.document import DatasetAttachmentReference


def register_dataset_usage_source(kind: str, name: str, source: UsageSource) -> None:
    from .usage import register_dataset_usage_source as register
    register(kind, name, source)

def register_dataset() -> None:
    from app.file_share import register_native_provider, register_resource_aliases
    from app.document import register_dataset_compatibility, refresh_dataset_projection, register_dataset_attachment_reader
    from .compatibility import LegacyDatasetAdapter
    from .projection import register_projection_writer
    from .provider import DatasetProvider, resolve_alias

    register_native_provider("data", DatasetProvider())
    register_resource_aliases("dataset", resolve_alias)
    register_dataset_compatibility(LegacyDatasetAdapter())
    register_projection_writer(refresh_dataset_projection)
    register_dataset_attachment_reader(read_attachment_reference)


async def read_attachment_reference(identity: UUID, actor: DataActor) -> DatasetAttachmentReference:
    from app.document import DatasetAttachmentReference
    from core.authorize import check_privilege
    from core.database import get_db
    from core.user import get_user_record
    from .service import record
    if not isinstance(actor, int) and not await check_privilege(await get_user_record(actor.user_id),
        ["DATASET_READ", "DATASET_EDIT", "DATASET_ADMIN"], get_db()):
        raise PermissionError("Dataset access denied")
    dataset = await record(identity, actor)
    return DatasetAttachmentReference(uri=f"data://{dataset.id}", title=dataset.title)
