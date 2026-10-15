"""A missing dedicated mount must never become a new empty authoritative store."""

import os
import tempfile
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from core.settings import settings
from core.util import complete_io

from .disk import sync_directory
from .models import FileStore


async def ensure_disk_identity(session: AsyncSession) -> None:
    # Serializes the first volume binding across concurrent registrations.
    await session.execute(text("SELECT pg_advisory_xact_lock(4729182036851)"))
    record = await session.scalar(select(FileStore).where(FileStore.code == "disk"))
    marker = Path(settings.GALARIS_FILE_ROOT) / ".store-uuid"

    def bind() -> UUID:
        if marker.is_symlink() or marker.parent.is_symlink():
            raise ValueError("Invalid managed file volume identity")
        if record is not None:
            if not marker.is_file() or marker.read_text().strip() != str(record.id):
                raise ValueError("Managed file volume missing or replaced; restore its original mount")
            return record.id
        marker.parent.mkdir(parents=True, exist_ok=True)
        if marker.exists():
            return UUID(marker.read_text().strip())
        identifier = uuid4()
        # A crash before commit can leave this marker: the next transaction
        # adopts the same UUID and can resume its transfer manifest.
        descriptor, name = tempfile.mkstemp(dir=marker.parent, prefix=".identity-", suffix=".part")
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w") as output:
                output.write(str(identifier))
                output.flush()
                os.fsync(output.fileno())
            os.link(temporary, marker)
        finally:
            temporary.unlink(missing_ok=True)
        sync_directory(marker.parent)
        sync_directory(marker.parent.parent)
        return identifier

    identifier = await complete_io(bind)
    if record is None:
        session.add(FileStore(id=identifier, code="disk"))
        await session.flush()
