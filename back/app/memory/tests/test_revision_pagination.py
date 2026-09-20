import pytest
from sqlalchemy import func, literal, select

from app.memory import service
from app.memory.models import MemoryRevision
from app.memory.schemas import MemoryItemCreate, MemoryPayload


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
