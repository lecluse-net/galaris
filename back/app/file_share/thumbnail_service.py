"""Inventory and prepare source-authorized catalogue derivatives for Dream."""

from typing import Any
from uuid import UUID
from hashlib import sha256

from sqlalchemy import Select, case, func, or_, select

from app.connection import Connection
from app.tools import ToolModel
from core.database import get_db
from core.document import OFFICE_EXTENSIONS
from core.preview import MODEL_EXTENSIONS, MODEL_TYPES

from .catalogue import live_catalogue_binding
from .catalogue_resources import thumbnail
from .models import FileCatalogEntry
from .resource_contracts import ResourceDescriptor


def pending_thumbnails(handled: Select[tuple[str]]) -> Select[tuple[FileCatalogEntry]]:
    media = func.lower(func.trim(func.split_part(FileCatalogEntry.descriptor["media_type"].as_string(), ";", 1)))
    name = func.lower(FileCatalogEntry.descriptor["name"].as_string())
    # Retry SVGs completed without a derivative by the former raster-only renderer.
    renderer = case((or_(media == "image/svg+xml", name.endswith(".svg")), ":svg-v1"), else_="")
    version = func.concat(FileCatalogEntry.source_version, ":", FileCatalogEntry.binding_stamp, ":", FileCatalogEntry.file_sha256, renderer)
    identity = func.concat("file:", FileCatalogEntry.id, ":", func.encode(func.sha256(func.convert_to(version, "UTF8")), "hex"))
    return select(FileCatalogEntry).join(Connection, Connection.id == FileCatalogEntry.connection_id).join(
        ToolModel, ToolModel.id == Connection.tool_id,
    ).where(
        FileCatalogEntry.present.is_(True), FileCatalogEntry.memory_node_id.is_not(None),
        FileCatalogEntry.file_sha256.is_not(None),
        FileCatalogEntry.descriptor["is_collection"].as_boolean().is_(False), live_catalogue_binding(),
        or_(media.startswith("image/"), media.startswith("video/"), media.startswith("text/"),
            media.in_({"application/pdf", "application/json", "application/xml", "application/javascript"} | MODEL_TYPES),
            *[name.endswith(suffix) for suffix in OFFICE_EXTENSIONS | MODEL_EXTENSIONS | {".pdf", ".svg"}]),
        identity.not_in(handled),
    )


async def count_pending(handled: Select[tuple[str]]) -> int:
    return int(await get_db().scalar(select(func.count()).select_from(pending_thumbnails(handled).subquery())) or 0)


async def next_source(handled: Select[tuple[str]]) -> dict[str, Any] | None:
    entry = await get_db().scalar(pending_thumbnails(handled).order_by(FileCatalogEntry.id).limit(1))
    if entry is None:
        return None
    descriptor = ResourceDescriptor.model_validate(entry.descriptor)
    renderer = ":svg-v1" if descriptor.media_type.split(";", 1)[0].strip().casefold() == "image/svg+xml" or descriptor.name.casefold().endswith(".svg") else ""
    version = sha256(f"{entry.source_version or ''}:{entry.binding_stamp}:{entry.file_sha256 or ''}{renderer}".encode()).hexdigest()
    return {"item_id": str(entry.memory_node_id), "entry_id": str(entry.id), "agent_id": entry.agent_id,
            "uri": entry.uri,
            "version": entry.source_version, "binding_stamp": entry.binding_stamp, "sha256": entry.file_sha256,
            "identity": f"file:{entry.id}:{version}"}


async def generate(source: dict[str, Any], *, force: bool = False) -> bool:
    entry = await get_db().get(FileCatalogEntry, UUID(source["entry_id"]))
    if entry is None or (entry.source_version, entry.binding_stamp, entry.file_sha256) != (
        source["version"], source["binding_stamp"], source["sha256"],
    ):
        return False
    try:
        result = await thumbnail(UUID(source["item_id"]), int(source["agent_id"]), entry.id, force=force)
    except (PermissionError, FileNotFoundError):
        return False
    return result is not None
