from fastapi import APIRouter, HTTPException, status
from typing import List

from core.authorize import authorize
from core.authorize import Privileges

from . import album_service
from .schemas import Album as AlbumSchema, AlbumCreate, AlbumUpdate

from loguru import logger

router = APIRouter(prefix="/albums", tags=["albums"])


@router.get("", response_model=List[AlbumSchema])
@authorize(privileges=[Privileges.ALBUM_ACCESS, Privileges.ALBUM_EDIT])
async def read_albums(
    skip: int = 0,
    limit: int = 100,
):
    """Liste tous les albums"""
    logger.info("Listing albums")
    albums = await album_service.get_albums(skip=skip, limit=limit)
    return albums


@router.get("/{album_id}", response_model=AlbumSchema)
@authorize(privileges=[Privileges.ALBUM_ACCESS, Privileges.ALBUM_EDIT])
async def read_album(
    album_id: int,
):
    """Récupère un album par son ID"""
    album = await album_service.get_album_by_id(album_id)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    return album


@router.post("", response_model=AlbumSchema, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.ALBUM_EDIT)
async def create_album_endpoint(
    album: AlbumCreate,
):
    """Crée un nouvel album"""
    new_album = await album_service.create_album(album)
    logger.info(f"Album created: {new_album.code}")
    return new_album


@router.put("/{album_id}", response_model=AlbumSchema)
@authorize(privileges=Privileges.ALBUM_EDIT)
async def update_album_endpoint(
    album_id: int,
    album_update: AlbumUpdate,
):
    """Met à jour un album existant"""
    album = await album_service.update_album(album_id, album_update)
    if album is None:
        raise HTTPException(status_code=404, detail="Album not found")
    logger.info(f"Album updated: {album.code}")
    return album


@router.delete("/{album_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.ALBUM_EDIT)
async def delete_album_endpoint(
    album_id: int,
):
    """Supprime (soft-delete) un album"""
    deleted = await album_service.delete_album(album_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Album not found")
    logger.info(f"Album deleted: {album_id}")
    return None
