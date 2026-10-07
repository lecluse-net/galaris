"""Schema cutover preserves content, permissions and resumable memory work."""

import json

import pytest
from sqlalchemy import select, text

from app.dream.models import DreamReceipt
from app.lab.models import LabEvaluationCase, LabEvaluationDataset
from app.memory.models import MemoryItem
from core.dbadmin import SchemaTransitionSet
from dbadmin_composition import (
    _memory_snapshots_normalized,
    _needs_memory_snapshot_normalization,
    _normalize_memory_snapshots,
)


def test_snapshot_normalization_follows_the_memory_schema_delta():
    assert not _needs_memory_snapshot_normalization(SchemaTransitionSet())
    assert not _needs_memory_snapshot_normalization(SchemaTransitionSet(
        removed_columns=frozenset({"other.unrelated"}),
    ))
    assert _needs_memory_snapshot_normalization(SchemaTransitionSet(
        removed_columns=frozenset({"memory_items.memory_type"}),
    ))


@pytest.mark.asyncio
async def test_snapshot_cutover_is_atomic_idempotent_and_preserves_authored_content(db):
    item = MemoryItem(title="Synthetic preference", resource_id="synthetic/resource",
        content_hash="0" * 64, visibility="public", source_managed=True,
        managed_source_kind="synthetic", managed_source_ref="synthetic:preference", read_only=True, metadata_={
            "memory_type": "core", "confirmed": True, "temporal": {"month": 9},
        })
    receipt = DreamReceipt(mechanism_key="memory.extract_task", subject_kind="task",
        subject_id="synthetic-subject", prepared_payload={
            "operations": [{"action": "CREATE", "title": "Synthetic fact",
                            "content": "<p>Preserved source content</p>", "memory_type": "semantic"}],
            "result": json.dumps({"memories": [{"memory_id": "synthetic-memory",
                "type": "social", "excerpt": "Preserved excerpt"}]}),
        })
    dataset = LabEvaluationDataset(name="Synthetic memory experiment", mechanism="memory_extraction",
        configuration={"schema": {"properties": {"memory_type": {"enum": ["core", "semantic"]},
                                                   "title": {"type": "string"},
                                                   "payload": {"type": "object", "default": {"memory_type": "core"},
                                                       "examples": [{"memory_type": "semantic"}],
                                                       "const": {"memoryTypes": ["social"]},
                                                       "enum": [{"memory_type": "working"}]}},
                                  "required": ["title", "memory_type"]},
                       "authored": "Discuss the memory_type identifier without rewriting this text."})
    db.add_all([item, receipt, dataset])
    await db.flush()
    delta = SchemaTransitionSet(removed_columns=frozenset({"memory_items.memory_type"}))
    assert not await _memory_snapshots_normalized(db, delta)
    with pytest.raises(RuntimeError, match="rollback proof"):
        async with db.begin_nested():
            await _normalize_memory_snapshots(db, delta)
            assert await _memory_snapshots_normalized(db, delta)
            raise RuntimeError("rollback proof")
    assert not await _memory_snapshots_normalized(db, delta)
    await _normalize_memory_snapshots(db, delta)
    await _normalize_memory_snapshots(db, delta)
    assert await _memory_snapshots_normalized(db, delta)
    await db.refresh(item)
    await db.refresh(receipt)
    await db.refresh(dataset)
    assert item.metadata_ == {"confirmed": True, "temporal": {"month": 9}}
    assert (item.title, item.resource_id, item.content_hash, item.visibility) == (
        "Synthetic preference", "synthetic/resource", "0" * 64, "public",
    )
    assert receipt.prepared_payload["operations"] == [{"action": "CREATE", "title": "Synthetic fact",
                                                       "content": "<p>Preserved source content</p>"}]
    assert json.loads(receipt.prepared_payload["result"]) == {"memories": [
        {"memory_id": "synthetic-memory", "excerpt": "Preserved excerpt"}]}
    assert dataset.configuration["schema"] == {
        "properties": {"title": {"type": "string"}, "payload": {
            "type": "object", "default": {"memory_type": "core"},
            "examples": [{"memory_type": "semantic"}], "const": {"memoryTypes": ["social"]},
            "enum": [{"memory_type": "working"}]}}, "required": ["title"],
    }
    assert dataset.configuration["authored"] == "Discuss the memory_type identifier without rewriting this text."
    assert await db.scalar(select(MemoryItem.id).where(MemoryItem.id == item.id)) == item.id
    assert not await db.scalar(text("""SELECT EXISTS (SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'memory_items' AND column_name = 'memory_type')"""))


@pytest.mark.asyncio
async def test_snapshot_cutover_preserves_json_content_keywords_and_other_lab_mechanisms(db):
    authored = {"memory_type": "semantic", "excerpt": "Synthetic authored record",
                "type": "social", "values": ["memory_type", "memoryTypes"]}
    encoded = json.dumps(authored, indent=2)
    authored_schema = {"properties": {"memory_type": {"enum": ["core", "semantic"]}}}
    encoded_result = json.dumps({"memories": [authored]}, indent=2)
    item = MemoryItem(title="Synthetic JSON discussion", resource_id="synthetic/json",
        content_hash="1" * 64, keywords=["memory_type", "memoryTypes"],
        visibility="public", source_managed=True, managed_source_kind="synthetic",
        managed_source_ref="synthetic:json", read_only=True,
        metadata_={"memory_type": "semantic", "authored": authored, "schema": authored_schema})
    receipt = DreamReceipt(mechanism_key="memory.extract_task", subject_kind="task",
        subject_id="synthetic-json-subject", prepared_payload={
            "operations": [{"action": "CREATE", "title": "Synthetic JSON fact",
                            "content": encoded, "memory_type": "semantic"}],
        })
    memory_dataset = LabEvaluationDataset(name="Synthetic JSON memory input",
        mechanism="memory_extraction", configuration={"authored": encoded, "result": encoded_result})
    other_dataset = LabEvaluationDataset(name="Synthetic JSON dispatcher input",
        mechanism="dispatcher", configuration={"schema": {"properties": {
            "memory_type": {"enum": ["core", "semantic"]}}}})
    db.add_all([item, receipt, memory_dataset, other_dataset])
    await db.flush()
    cases = [LabEvaluationCase(dataset_id=dataset.id, name="Synthetic JSON case",
        input_data={"variable_value": authored, "context": {"existing_memories": [{
            "id": "synthetic-memory", "title": "Synthetic JSON fact", "content": encoded,
            "memory_type": "semantic"}]}},
        expected_output=authored, reference={"authored": encoded, "schema": authored_schema},
        source_capture={"input_data": {"context": {"existing_memories": [authored]}}})
        for dataset in (memory_dataset, other_dataset)]
    db.add_all(cases)
    await db.flush()
    delta = SchemaTransitionSet(removed_columns=frozenset({"memory_items.memory_type"}))
    await _normalize_memory_snapshots(db, delta)
    await _normalize_memory_snapshots(db, delta)
    assert await _memory_snapshots_normalized(db, delta)
    for record in (item, receipt, memory_dataset, other_dataset, *cases):
        await db.refresh(record)
    assert item.keywords == ["memory_type", "memoryTypes"]
    assert item.metadata_ == {"authored": authored, "schema": authored_schema}
    assert receipt.prepared_payload["operations"][0]["content"] == encoded
    assert "memory_type" not in receipt.prepared_payload["operations"][0]
    assert memory_dataset.configuration == {"authored": encoded, "result": encoded_result}
    assert other_dataset.configuration == {"schema": {"properties": {
        "memory_type": {"enum": ["core", "semantic"]}}}}
    for case in cases:
        expected_memory = {"id": "synthetic-memory", "title": "Synthetic JSON fact", "content": encoded}
        if case.dataset_id == other_dataset.id:
            expected_memory["memory_type"] = "semantic"
        assert case.input_data == {"variable_value": authored, "context": {"existing_memories": [expected_memory]}}
        assert case.expected_output == authored
        assert case.reference == {"authored": encoded, "schema": authored_schema}
        assert case.source_capture == {"input_data": {"context": {"existing_memories": [authored]}}}
