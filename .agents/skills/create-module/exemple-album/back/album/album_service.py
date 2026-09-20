"""
Service pour la gestion des albums.

Usage:
    >>> from app.album.album_service import get_albums, get_album_by_id, create_album
    >>> albums = await get_albums()
    >>> album = await get_album_by_id(1)
"""

from sqlalchemy import select
from typing import List, Optional
from core.database import get_db
from core import websocket
from core.authorize import authorize, Privileges
from .models import Album
from .schemas import AlbumCreate, AlbumUpdate, Album as AlbumSchema


@authorize(privileges=[Privileges.ALBUM_ACCESS])
class AlbumRoom(websocket.BaseRoom):
    """
    Cette classe représente le salon de discussion pour un album spécifique.
    Le décorateur s'assurera que l'utilisateur a le privilège requis
    pour rejoindre ce flux.
    """
    pass


async def get_albums(skip: int = 0, limit: int = 100) -> List[Album]:
    """Récupère tous les albums non supprimés."""
    db = get_db()
    query = select(Album).offset(skip).limit(limit)
    query = Album.histo_filter(query)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_album_by_id(album_id: int) -> Optional[Album]:
    """Récupère un album par son ID."""
    db = get_db()
    query = select(Album).where(Album.id == album_id)
    query = Album.histo_filter(query)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def get_album_by_code(code: str) -> Optional[Album]:
    """Récupère un album par son code."""
    db = get_db()
    query = select(Album).where(Album.code == code)
    query = Album.histo_filter(query)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_album(album_data: AlbumCreate) -> Album:
    """Crée un nouvel album."""
    # Vérifier si le code existe déjà
    existing = await get_album_by_code(album_data.code)
    if existing:
        raise ValueError(f"Album code already exists: {album_data.code}")

    data = album_data.model_dump()
    album = Album(**data)

    db = get_db()
    db.add(album)
    await db.commit()
    await db.refresh(album)

    # Émettre l'événement websocket vers la room de l'utilisateur créateur
    # La room est basée sur created_by pour que tous les clients de cet utilisateur reçoivent les événements
    room = AlbumRoom(album.created_by)
    await websocket.emit("album", "create", AlbumSchema.model_validate(album).model_dump(mode="json"), room)

    return album


async def update_album(album_id: int, album_update: AlbumUpdate) -> Optional[Album]:
    """Met à jour un album existant."""
    album = await get_album_by_id(album_id)
    if album is None:
        return None

    update_data = album_update.model_dump(exclude_unset=True)

    # Si on change le code, vérifier qu'il n'existe pas déjà
    if "code" in update_data and update_data["code"] != album.code:
        existing = await get_album_by_code(update_data["code"])
        if existing:
            raise ValueError(f"Album code already exists: {update_data['code']}")

    for key, value in update_data.items():
        setattr(album, key, value)

    db = get_db()
    await db.commit()
    await db.refresh(album)

    # Émettre l'événement websocket vers la room de l'utilisateur créateur
    room = AlbumRoom(album.created_by)
    await websocket.emit("album", "update", AlbumSchema.model_validate(album).model_dump(mode="json"), room)

    return album


async def delete_album(album_id: int) -> bool:
    """Supprime (soft-delete) un album."""
    album = await get_album_by_id(album_id)
    if album is None:
        return False

    # Sauvegarder le created_by avant le soft_delete
    created_by = album.created_by

    album.soft_delete()

    db = get_db()
    await db.commit()

    # Émettre l'événement websocket vers la room de l'utilisateur créateur
    room = AlbumRoom(created_by)
    await websocket.emit("album", "delete", {"id": album_id}, room)

    return True
