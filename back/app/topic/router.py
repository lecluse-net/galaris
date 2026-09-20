"""Administration API for global thematic dossiers."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from core.authorize import Privileges, authorize
from app.agent import current_management_scope
from app.connection.facade import get_connection

from . import service
from .schemas import (
    TopicContentRead,
    TopicCreate,
    TopicLinkedMemoryRead,
    TopicMergeRequest,
    TopicMutationResult,
    TopicPage,
    TopicRead,
    TopicRef,
    TopicSplitRequest,
    TopicUpdate,
)


router = APIRouter(prefix="/topics", tags=["topics"])


async def _require_global_scope() -> None:
    if not (await current_management_scope()).is_global:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global Agent management is required",
        )


@router.get("", response_model=TopicPage)
@authorize(privileges=[Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT])
async def read_topics(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=500),
    q: str | None = Query(default=None, max_length=500),
    month: str | None = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
) -> TopicPage:
    scope = await current_management_scope()
    return await service.list_page(
        skip=skip,
        limit=limit,
        search=q,
        month=month,
        agent_ids=scope.agent_ids,
    )


@router.get("/conversation", response_model=list[TopicRead])
@authorize(privileges=[Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT])
async def read_conversation_topics(
    connection_id: int = Query(gt=0),
    room_id: str = Query(min_length=1, max_length=512),
) -> list[TopicRead]:
    connection = await get_connection(connection_id)
    scope = await current_management_scope()
    if connection is None or not scope.allows(connection.agent_id):
        raise HTTPException(status_code=404, detail="Conversation not found")
    return await service.list_for_conversation(
        connection_id=connection_id, room_id=room_id
    )


@router.get("/keywords", response_model=list[str])
@authorize(privileges=[Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT])
async def read_topic_keywords() -> list[str]:
    return await service.list_keywords()


@router.get("/refs", response_model=list[TopicRef])
@authorize(
    privileges=[Privileges.TASK_ACCESS, Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT]
)
async def read_topic_refs(
    ids: list[UUID] = Query(default_factory=list, max_length=500),
) -> list[TopicRef]:
    """Resolve badge labels in one bounded request without loading Topic analytics."""

    return await service.list_refs(set(ids))


@router.post("", response_model=TopicRead, status_code=status.HTTP_201_CREATED)
@authorize(privileges=Privileges.TOPIC_EDIT)
async def create_topic(data: TopicCreate) -> TopicRead:
    await _require_global_scope()
    return await service.create(data)


def _mutation_error(exc: Exception) -> HTTPException:
    if isinstance(exc, service.TopicNotFoundError):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/{topic_id}/memories", response_model=list[TopicLinkedMemoryRead])
@authorize(privileges=Privileges.TOPIC_EDIT)
async def read_topic_memories(topic_id: UUID) -> list[TopicLinkedMemoryRead]:
    try:
        scope = await current_management_scope()
        return await service.list_linked_memories_in_scope(
            topic_id,
            agent_ids=scope.agent_ids,
        )
    except service.TopicNotFoundError as exc:
        raise _mutation_error(exc) from exc


@router.get("/{topic_id}/content", response_model=TopicContentRead)
@authorize(privileges=[Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT])
async def read_topic_content(
    topic_id: UUID,
    limit: int = Query(default=50, ge=1, le=500),
) -> TopicContentRead:
    try:
        scope = await current_management_scope()
        return await service.get_content(
            topic_id,
            limit=limit,
            agent_ids=scope.agent_ids,
        )
    except service.TopicNotFoundError as exc:
        raise _mutation_error(exc) from exc


@router.put("/{topic_id}", response_model=TopicRead)
@authorize(privileges=Privileges.TOPIC_EDIT)
async def update_topic(topic_id: UUID, data: TopicUpdate) -> TopicRead:
    try:
        await _require_global_scope()
        return await service.update_topic(topic_id, data)
    except HTTPException:
        raise
    except (service.TopicNotFoundError, service.TopicConflictError) as exc:
        raise _mutation_error(exc) from exc


@router.post("/{topic_id}/merge", response_model=TopicMutationResult)
@authorize(privileges=Privileges.TOPIC_EDIT)
async def merge_topic(
    topic_id: UUID, data: TopicMergeRequest
) -> TopicMutationResult:
    try:
        await _require_global_scope()
        return await service.merge(topic_id, data.target_topic_id)
    except HTTPException:
        raise
    except (service.TopicNotFoundError, service.TopicConflictError) as exc:
        raise _mutation_error(exc) from exc


@router.post(
    "/{topic_id}/split",
    response_model=TopicMutationResult,
    status_code=status.HTTP_201_CREATED,
)
@authorize(privileges=Privileges.TOPIC_EDIT)
async def split_topic(
    topic_id: UUID, data: TopicSplitRequest
) -> TopicMutationResult:
    try:
        await _require_global_scope()
        return await service.split(topic_id, data)
    except HTTPException:
        raise
    except (service.TopicNotFoundError, service.TopicConflictError) as exc:
        raise _mutation_error(exc) from exc


@router.delete("/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
@authorize(privileges=Privileges.TOPIC_EDIT)
async def delete_topic(topic_id: UUID) -> None:
    await _require_global_scope()
    if not await service.delete_topic(topic_id):
        raise HTTPException(status_code=404, detail="Topic not found")


@router.get("/{topic_id}", response_model=TopicRead)
@authorize(privileges=[Privileges.TOPIC_ACCESS, Privileges.TOPIC_EDIT])
async def read_topic(topic_id: UUID) -> TopicRead:
    topic = await service.get(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="Topic not found")
    return topic
