import pytest
from sqlalchemy import func, insert, literal, select

from app.memory import service
from app.memory.models import MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryPayload
from app.task.models import Task, TaskStatus


@pytest.mark.asyncio
async def test_large_history_only_materializes_the_requested_revision_page(db, agents, memory_storage):
    item, _ = await service.create_item(MemoryItemCreate(owner_agent_id=agents[0].id, title="History", memory_type="working", node_kind="document", payload=MemoryPayload(text="content")))
    table = MemoryRevision.__table__
    series = func.generate_series(2, 1001).table_valued("number").render_derived()
    expressions = [func.gen_random_uuid() if column.name == "id" else series.c.number if column.name == "revision" else column
                   for column in table.columns]
    await db.execute(table.insert().from_select([column.name for column in table.columns],
        select(*expressions).select_from(table.join(series, literal(True))).where(table.c.item_id == item.id, table.c.revision == 1)))
    await db.commit()
    page = await service.list_document_content_revisions(item.id, actor_agent_id=agents[0].id, limit=50, offset=50)
    assert page.total == 1001 and len(page.items) == 50 and page.has_more
    assert [entry.revision for entry in page.items] == list(range(951, 901, -1))
    assert sum(isinstance(value, MemoryRevision) for value in db.identity_map.values()) <= 51
    generic = await service.list_revisions(item.id, agent_id=agents[0].id, limit=20, offset=50)
    assert [entry.revision for entry in generic] == list(range(51, 71))


@pytest.mark.asyncio
async def test_legacy_version_reads_agree_with_history_and_preserve_content(db, agents, memory_storage):
    owner = agents[0]
    task = Task(label="Legacy content versions", status=TaskStatus.EXEC, agent_id=owner.id)
    db.add(task)
    await db.flush()
    item, _ = await service.create_item(MemoryItemCreate(
        owner_agent_id=owner.id, title="Legacy history", memory_type="working",
        node_kind="document", media_type="text/html", payload=MemoryPayload(text="<p>Original content</p>")))
    template = dict(item_id=item.id, provider_code=item.provider_code, resource_id=item.resource_id,
                    title=item.title, content_type=item.content_type, media_type=item.media_type,
                    document_content_version=None, task_id=task.id)
    await db.execute(insert(MemoryRevision), [
        dict(template, revision=2, content_hash=item.content_hash),  # No content change.
        dict(template, revision=4, content_hash="changed"),  # Noncontiguous legacy versions.
        dict(template, revision=5, content_hash="other", document_content_version=False),
        dict(template, revision=6, content_hash="other"),  # Compare to the immediate revision.
        dict(template, revision=7, content_hash="human", task_id=None),
    ])
    await db.commit()
    page = await service.list_document_content_revisions(item.id, actor_agent_id=owner.id)
    assert [row.revision for row in page.items] == [4, 1]
    for revision in (1, 4):
        version = await service.get_document_content_revision(item.id, revision, actor_agent_id=owner.id)
        assert version.content == "<p>Original content</p>"
    for revision in (2, 3, 5, 6, 7):
        with pytest.raises(service.MemoryNotFoundError):
            await service.get_document_content_revision(item.id, revision, actor_agent_id=owner.id)
