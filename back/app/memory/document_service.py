"""Collaborative operations for HTML and JSON Dataset documents."""

from __future__ import annotations

import re
from typing import Literal
from uuid import UUID

from sqlalchemy.orm.exc import StaleDataError

from app.agent import Agent
from core.database import get_db
from core.util import normalize_html, read_html_page, replace_visible_text, html_blocks, visible_text

from . import service
from .models import MemoryItem
from .document_types import DocumentType
from .schemas import (
    MemoryGrantUpdate,
    MemoryItemCreate,
    MemoryItemUpdate,
    MemoryPayload,
    MemorySourceCreate,
)


DocumentAccess = Literal["read", "edit", "none"]

_READ_MAX_CHARS = 2_000_000
_EDIT_MATCH_MAX_CHARS = 100_000
_EDIT_CONTENT_MAX_CHARS = 500_000
_QUERY_MAX_CHARS = 500
_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)


def _assert_document(item: MemoryItem) -> None:
    if item.node_kind != "document":
        raise service.MemoryConflictError("The selected memory is not a document.")


def _decode_document(content: bytes) -> str:
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise service.MemoryConflictError(
            "A working document must contain UTF-8 text."
        ) from exc


def _normalize_document_path(path: str) -> str:
    """Normalize one logical document folder without accepting traversal segments."""

    parts: list[str] = []
    for raw_part in path.strip().replace("\\", "/").split("/"):
        part = raw_part.strip()
        if not part:
            continue
        if part in {".", ".."}:
            raise ValueError("A document folder cannot contain '.' or '..'.")
        parts.append(part)
    normalized = "/".join(parts)
    if len(normalized) > 500:
        raise ValueError("A document folder cannot exceed 500 characters.")
    return normalized


def _query_start(content: str, query: str) -> int:
    """Locate one useful deterministic passage without another model call."""

    normalized = query.strip()[:_QUERY_MAX_CHARS]
    if not normalized:
        return 0
    folded_content = content.casefold()
    exact = folded_content.find(normalized.casefold())
    if exact >= 0:
        return content.rfind("\n", 0, exact) + 1

    terms = {
        token.casefold()
        for token in _TOKEN_RE.findall(normalized)
        if len(token) >= 2
    }
    if not terms:
        return 0
    best_start = 0
    best_score = 0
    start = 0
    for match in re.finditer(r"\n\s*\n", content):
        end = match.start()
        paragraph_terms = {
            token.casefold() for token in _TOKEN_RE.findall(content[start:end])
        }
        score = len(terms & paragraph_terms)
        if score > best_score:
            best_start = start
            best_score = score
        start = match.end()
    paragraph_terms = {
        token.casefold() for token in _TOKEN_RE.findall(content[start:])
    }
    if len(terms & paragraph_terms) > best_score:
        best_start = start
    return best_start


def _mutation_payload(item: MemoryItem, *, state: str) -> dict[str, object]:
    return {
        "document_id": str(item.id),
        "title": item.title,
        "revision": item.revision,
        "state": state,
        "size_bytes": item.size_bytes,
    }


async def _is_immediate_append_retry(
    item: MemoryItem,
    *,
    actor_agent_id: int,
    task_id: UUID | None,
    current: str,
    content: str,
) -> bool:
    """Recognize the exact last append without mistaking a pre-existing suffix."""

    if task_id is None or item.revision < 2:
        return False
    latest = next(
        (
            revision
            for revision in reversed(item.revisions)
            if revision.revision == item.revision
        ),
        None,
    )
    if (
        latest is None
        or not latest.document_append
        or latest.author_agent_id != actor_agent_id
        or latest.task_id != task_id
    ):
        return False
    # The latest content row identifies the exact append and task. Metadata,
    # sharing and attachment writes never create competing document revisions.
    return current.endswith(content)


async def create_document(
    *,
    owner_agent_id: int,
    title: str,
    content: str,
    task_id: UUID | None,
    folder: str = "",
    keywords: list[str] | None = None,
    metadata: dict[str, object] | None = None,
    deletion_protected: bool = False,
    document_type: DocumentType = "html",
) -> MemoryItem:
    """Create a private, mutable, non-deduplicated working document."""

    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("A document title is required.")
    normalized_folder = _normalize_document_path(folder)
    source = (
        MemorySourceCreate(
            source_kind="task",
            source_ref=f"task:{task_id}",
            excerpt=content[:1_000],
            metadata={"node_kind": "document"},
        )
        if task_id is not None
        else None
    )
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=owner_agent_id,
            title=normalized_title,
            payload=MemoryPayload(text=content),
            memory_type="working",
            node_kind="document",
            content_type="text",
            document_type=document_type,
            media_type="application/json" if document_type == "dataset" else "text/html",
            keywords=keywords or [],
            metadata={
                **(metadata or {}),
                **(
                    {"document_path": normalized_folder}
                    if normalized_folder
                    else {}
                ),
            },
            visibility="private",
            source=source,
        ),
        actor_task_id=task_id,
        deletion_protected=deletion_protected,
        deduplicate=False,
    )
    return item


async def create_user_document(
    *,
    owner_user_id: int,
    editor_agent_id: int,
    title: str,
    content: str,
    folder: str = "",
    document_type: DocumentType = "html",
) -> MemoryItem:
    """Create a private User-owned document without an implicit Agent grant."""

    normalized_title = title.strip()
    if not normalized_title:
        raise ValueError("A document title is required.")
    normalized_folder = _normalize_document_path(folder)
    item, _created = await service.create_item(
        MemoryItemCreate(
            owner_agent_id=editor_agent_id,
            title=normalized_title,
            payload=MemoryPayload(text=content),
            memory_type="working",
            node_kind="document",
            content_type="text",
            document_type=document_type,
            media_type="application/json" if document_type == "dataset" else "text/html",
            keywords=[],
            metadata=(
                {"document_path": normalized_folder}
                if normalized_folder
                else {}
            ),
            visibility="private",
        ),
        deduplicate=False,
        owner_user_id=owner_user_id,
    )
    return item


async def read_document(
    document_id: UUID,
    *,
    actor_agent_id: int,
    task_id: UUID | None,
    query: str = "",
    offset: int = 0,
    max_chars: int = 20_000,
) -> dict[str, object]:
    """Return one bounded passage and a continuation offset."""

    item, raw_content, access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
        record_llm_access=True,
        task_id=task_id,
    )
    _assert_document(item)
    content = _decode_document(raw_content)
    if _media_type == "text/html":
        blocks = html_blocks(content)
        start_block = max(0, offset)
        if query.strip():
            start_block = next((index for index, block in enumerate(blocks) if query.casefold() in visible_text(block).casefold()), 0)
        return {
            "document_id": str(item.id), "title": item.title, "revision": item.revision,
            "document_type": item.document_type,
            "can_write": access.can_write, "content_profile": item.content_profile,
            **read_html_page(content, offset=start_block, max_chars=max(1, min(max_chars, _READ_MAX_CHARS))),
        }
    limit = max(1, min(max_chars, _READ_MAX_CHARS))
    start = _query_start(content, query) if query.strip() else max(0, offset)
    start = min(start, len(content))
    end = min(len(content), start + limit)
    return {
        "document_id": str(item.id),
        "title": item.title,
        "revision": item.revision,
        "content": content[start:end],
        "document_type": item.document_type,
        "media_type": _media_type,
        "offset_unit": "character",
        "start": start,
        "end": end,
        "total": len(content),
        "next_offset": end if end < len(content) else None,
        "can_write": access.can_write,
    }


async def edit_document(
    document_id: UUID,
    *,
    actor_agent_id: int,
    task_id: UUID | None,
    old_text: str,
    new_text: str,
) -> dict[str, object]:
    """Replace one exact unique passage with optimistic concurrency."""

    if not old_text:
        raise ValueError("old_text must not be empty.")
    if len(old_text) > _EDIT_MATCH_MAX_CHARS:
        raise ValueError(
            f"old_text exceeds {_EDIT_MATCH_MAX_CHARS} characters."
        )
    if len(new_text) > _EDIT_CONTENT_MAX_CHARS:
        raise ValueError(
            f"new_text exceeds {_EDIT_CONTENT_MAX_CHARS} characters."
        )
    item, raw_content, access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
    )
    _assert_document(item)
    if not access.can_write:
        raise service.MemoryPermissionError("Document edit access denied.")
    content = _decode_document(raw_content)
    occurrences = (visible_text(content) if _media_type == "text/html" else content).count(old_text)
    if occurrences == 0:
        raise service.MemoryConflictError(
            "old_text was not found. Read the current document and retry with an exact passage."
        )
    if occurrences > 1:
        raise service.MemoryConflictError(
            "old_text is ambiguous. Read a larger unique passage and retry."
        )
    updated_content = (replace_visible_text(content, old_text, new_text) if _media_type == "text/html" else content.replace(old_text, new_text, 1))
    try:
        updated = await service.update_item(
            document_id,
            MemoryItemUpdate(
                expected_revision=item.revision,
                payload=MemoryPayload(text=updated_content),
            ),
            actor_agent_id=actor_agent_id,
            actor_task_id=task_id,
            document_revision_author_agent_id=actor_agent_id,
        )
    except StaleDataError as exc:
        raise service.MemoryConflictError(
            "The document changed concurrently. Read it again and retry."
        ) from exc
    return _mutation_payload(updated, state="edited")


async def append_document(
    document_id: UUID,
    *,
    actor_agent_id: int,
    task_id: UUID | None,
    content: str,
    expected_revision: int | None = None,
) -> dict[str, object]:
    """Append one bounded passage, suppressing an immediate retry."""

    if not content:
        raise ValueError("Append content must not be empty.")
    if len(content) > _EDIT_CONTENT_MAX_CHARS:
        raise ValueError(
            f"Append content exceeds {_EDIT_CONTENT_MAX_CHARS} characters."
        )
    item, raw_content, access, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=actor_agent_id,
    )
    _assert_document(item)
    if not access.can_write:
        raise service.MemoryPermissionError("Document edit access denied.")
    current = _decode_document(raw_content)
    if _media_type == "text/html":
        content = normalize_html(content, profile=item.content_profile)
    if await _is_immediate_append_retry(
        item,
        actor_agent_id=actor_agent_id,
        task_id=task_id,
        current=current,
        content=content,
    ):
        return _mutation_payload(item, state="unchanged")
    if expected_revision is not None and expected_revision != item.revision:
        raise service.MemoryConflictError("The document changed; read it and retry with its revision.")
    try:
        updated = await service.update_item(
            document_id,
            MemoryItemUpdate(
                expected_revision=item.revision,
                payload=MemoryPayload(text=current + content),
            ),
            actor_agent_id=actor_agent_id,
            actor_task_id=task_id,
            document_revision_author_agent_id=actor_agent_id,
            document_append=True,
        )
    except StaleDataError as exc:
        raise service.MemoryConflictError(
            "The document changed concurrently. Read it again and retry."
        ) from exc
    return _mutation_payload(updated, state="appended")


async def share_document(
    document_id: UUID,
    *,
    owner_agent_id: int,
    target_agent_id: int,
    access: DocumentAccess,
    task_id: UUID | None,
) -> dict[str, object]:
    """Set or remove one collaborator grant; only the owner may call it."""

    item, _content, _effective, _content_type, _media_type = await service.get_item(
        document_id,
        agent_id=owner_agent_id,
    )
    _assert_document(item)
    if item.owner_agent_id != owner_agent_id:
        raise service.MemoryPermissionError(
            "Only the document owner can change collaborators."
        )
    if target_agent_id == owner_agent_id:
        raise service.MemoryConflictError(
            "The document owner already has edit access."
        )
    if await get_db().get(Agent, target_agent_id) is None:
        raise service.MemoryNotFoundError("Target agent not found.")
    if access == "none":
        updated = await service.remove_item_grant(
            document_id,
            target_agent_id,
            actor_agent_id=owner_agent_id,
            actor_task_id=task_id,
        )
    else:
        updated = await service.set_item_grant(
            document_id,
            target_agent_id,
            MemoryGrantUpdate(can_write=access == "edit"),
            actor_agent_id=owner_agent_id,
            actor_task_id=task_id,
        )
    return {
        "document_id": str(updated.id),
        "revision": updated.revision,
        "shared_with": [
            {
                "agent_id": grant.agent_id,
                "access": "edit" if grant.can_write else "read",
            }
            for grant in sorted(updated.grants, key=lambda value: value.agent_id)
        ],
    }


__all__ = [
    "DocumentAccess",
    "append_document",
    "create_document",
    "create_user_document",
    "edit_document",
    "read_document",
    "share_document",
]
