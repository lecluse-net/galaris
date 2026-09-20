from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

from app.topic import service
from app.topic.schemas import TopicCandidate, TopicClassification


@pytest.mark.asyncio
@pytest.mark.parametrize("proposed,existing,reuse", [
    ("旅行计划", "数据库备份", False),
    ("🚀", "🎉", False),
    ("☀️", "🌧️", False),
    ("旅行计划", "旅行计划", True),
    ("Резервное копирование", "Резервное копирование", True),
    ("Éducation", "education", True),
    ("दिन", "दीन", False),
])
async def test_unicode_topic_reuse(monkeypatch, proposed, existing, reuse):
    candidate = TopicCandidate(id=uuid4(), title=existing, keywords=[])
    monkeypatch.setattr(service, "list_candidates", AsyncMock(return_value=[candidate]))
    result, topic_id = await service.prefer_reuse(TopicClassification(action="create", title=proposed))
    assert (result.action == "reuse") is reuse
    assert topic_id == (candidate.id if reuse else None)
