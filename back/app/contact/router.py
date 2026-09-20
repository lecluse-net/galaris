"""RBAC-protected administration API for canonical contacts."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.agent import current_management_scope
from app.memory import (
    MemoryConflictError,
    MemoryNotFoundError,
    get_messenger_contact,
)
from core.authorize import Privileges, authorize

from . import service
from .schemas import (
    ContactForgetResult,
    ContactMergeRequest,
    ContactMergeResult,
    ContactPage,
)


router = APIRouter(prefix="/contacts", tags=["contacts"])


async def _require_agent_scope(agent_id: int) -> None:
    if not (await current_management_scope()).allows(agent_id):
        raise HTTPException(status_code=404, detail="Agent not found")


def _mutation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MemoryNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("", response_model=ContactPage)
@authorize(
    privileges=[Privileges.MEMORY_ACCESS, Privileges.MEMORY_EDIT, Privileges.MEMORY_ADMIN]
)
async def read_contacts(
    agent_id: int = Query(gt=0),
    q: str = Query(default="", max_length=500),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> ContactPage:
    await _require_agent_scope(agent_id)
    return await service.list_contacts(
        agent_id=agent_id,
        query=q,
        limit=limit,
        offset=offset,
    )


@router.post("/{source_contact_item_id}/merge", response_model=ContactMergeResult)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def merge_contacts(
    source_contact_item_id: UUID, data: ContactMergeRequest
) -> ContactMergeResult:
    try:
        source = await get_messenger_contact(source_contact_item_id)
        if source is None:
            raise MemoryNotFoundError("Source contact not found.")
        await _require_agent_scope(source.owner_agent_id)
        result = await service.merge_contacts(
            source_contact_item_id=source_contact_item_id,
            target_contact_item_id=data.target_contact_item_id,
        )
        return result
    except (MemoryNotFoundError, MemoryConflictError) as exc:
        raise _mutation_error(exc) from exc


@router.delete("/{contact_item_id}", response_model=ContactForgetResult)
@authorize(privileges=Privileges.MEMORY_EDIT)
async def forget_contact(contact_item_id: UUID) -> ContactForgetResult:
    try:
        contact = await get_messenger_contact(contact_item_id)
        if contact is None:
            raise MemoryNotFoundError("Contact not found.")
        await _require_agent_scope(contact.owner_agent_id)
        return await service.forget_contact(contact_item_id=contact_item_id)
    except (MemoryNotFoundError, MemoryConflictError) as exc:
        raise _mutation_error(exc) from exc


__all__ = ["router"]
