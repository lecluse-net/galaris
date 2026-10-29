"""Dataset-owned embedding generations, prepared outside database transactions."""

from __future__ import annotations

import math
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, delete, exists, func, select
from sqlalchemy.sql.elements import ColumnElement

from app.llm import ConfiguredEmbeddingModel, require_configured_embedding_model
from core.database import get_db

from .models import Dataset, DatasetSearchChunk, DatasetSearchIndex
from .passages import embedding_passages


MAX_CHUNKS = 2048
INDEX_VERSION = 1


def current_index(model_key: str) -> ColumnElement[bool]:
    index = DatasetSearchIndex
    count = select(func.count()).select_from(DatasetSearchChunk).where(
        DatasetSearchChunk.index_id == index.id).correlate(index).scalar_subquery()
    return and_(index.dataset_id == Dataset.id, index.model_key == model_key,
        index.index_version == INDEX_VERSION,
        index.source_revision == Dataset.revision, index.source_title == Dataset.title,
        index.source_keywords == Dataset.keywords,
        index.source_summary == func.coalesce(Dataset.summary_content, ""),
        index.chunk_count == count, ~exists(select(DatasetSearchChunk.id).where(
            DatasetSearchChunk.index_id == index.id,
            func.vector_dims(DatasetSearchChunk.embedding) != index.dimensions).correlate(index)))


def _subject(model_key: str) -> ColumnElement[str]:
    # lock_version covers every indexing input, including concurrent summaries.
    return func.concat(Dataset.id, ":", Dataset.lock_version, ":", model_key)


def pending(model_key: str, handled: Select[tuple[str]]) -> Select[tuple[Dataset]]:
    valid = exists(select(DatasetSearchIndex.id).where(current_index(model_key)))
    return select(Dataset).where(~valid, ~_subject(model_key).in_(handled))


async def count_pending(model_key: str, handled: Select[tuple[str]]) -> int:
    return int(await get_db().scalar(select(func.count()).select_from(pending(model_key, handled).subquery())) or 0)


async def claim_one(model_key: str, handled: Select[tuple[str]]) -> str | None:
    dataset = await get_db().scalar(pending(model_key, handled).order_by(Dataset.id)
        .limit(1).with_for_update(skip_locked=True))
    return f"{dataset.id}:{dataset.lock_version}:{model_key}" if dataset else None


def _source(dataset: Dataset) -> dict[str, Any]:
    return {"revision": dataset.revision, "title": dataset.title,
            "keywords": list(dataset.keywords), "summary": dataset.summary_content or ""}


async def source(subject: str) -> dict[str, Any] | None:
    identity, version, _ = subject.split(":")
    dataset = await get_db().scalar(select(Dataset).where(Dataset.id == UUID(identity), Dataset.lock_version == int(version)))
    if dataset is None:
        return None
    return {**_source(dataset), "content": dataset.content}


async def prepare(snapshot: dict[str, Any], model: ConfiguredEmbeddingModel) -> dict[str, Any]:
    passages = embedding_passages(snapshot["content"])
    if len(passages) > MAX_CHUNKS:
        raise ValueError("Dataset exceeds the semantic passage budget; lexical discovery remains available")
    prefix = f"Title: {snapshot['title']}\nKeywords: {', '.join(snapshot['keywords'])}\nDescription: {snapshot['summary']}"
    vectors: list[list[float]] = []
    for offset in range(0, len(passages), 32):
        texts = [f"{prefix}\nJSON pointer: {p.json_pointer}\n{p.text}" for p in passages[offset:offset + 32]]
        batch = await model.embed(texts, timeout=60.0)
        if len(batch) != len(texts):
            raise ValueError("Incomplete Dataset embedding response")
        vectors.extend(batch)
    dimensions = len(vectors[0]) if vectors else 0
    if not dimensions or any(len(v) != dimensions or not all(math.isfinite(x) for x in v)
                             or not any(x != 0 for x in v) for v in vectors):
        raise ValueError("Invalid Dataset embedding response")
    return {"source": {key: snapshot[key] for key in ("revision", "title", "keywords", "summary")},
            "model_key": model.key, "dimensions": dimensions,
            "chunks": [{"json_pointer": p.json_pointer, "text": p.text, "embedding": v}
                       for p, v in zip(passages, vectors, strict=True)]}


async def apply(subject: str, payload: dict[str, Any]) -> bool:
    identity, version, model_key = subject.split(":")
    model = await require_configured_embedding_model()
    if model.key != model_key or payload["model_key"] != model_key:
        return False
    dataset = await get_db().scalar(select(Dataset).where(Dataset.id == UUID(identity), Dataset.lock_version == int(version))
        .with_for_update().execution_options(populate_existing=True))
    if dataset is None or _source(dataset) != payload["source"]:
        return False
    # All chunks and the manifest publish in the caller's single transaction.
    old = await get_db().scalar(select(DatasetSearchIndex).where(DatasetSearchIndex.dataset_id == dataset.id))
    if old is not None:
        await get_db().execute(delete(DatasetSearchChunk).where(DatasetSearchChunk.index_id == old.id))
        await get_db().delete(old)
        await get_db().flush()
    index = DatasetSearchIndex(dataset_id=dataset.id, source_revision=dataset.revision,
        source_title=dataset.title, source_keywords=dataset.keywords, source_summary=dataset.summary_content or "",
        model_key=model_key, dimensions=payload["dimensions"], chunk_count=len(payload["chunks"]))
    get_db().add(index)
    await get_db().flush()
    for ordinal, chunk in enumerate(payload["chunks"]):
        get_db().add(DatasetSearchChunk(index_id=index.id, chunk_index=ordinal, **chunk))
    await get_db().flush()
    return True
