"""Agent directory URIs read live profiles without creating library documents."""

import json
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.agent import agent_service, tools
from app.agent.schemas import Agent as AgentPublic
from app.file_share import resource_service as files
from app.file_share.resource_contracts import ResourceContext
from app.memory.models import DocumentTag, MemoryItem


@pytest.mark.asyncio
async def test_directory_profile_uri_is_live_without_documents(db, agents, monkeypatch):
    owner, peer = agents
    await db.refresh(owner, attribute_names=["title"])
    owner.title.gender = "F"
    owner.personality = "<p>Calme et <strong>précise</strong>.</p>"
    owner.job_description = "<p>Accompagner les équipes.</p>"
    await db.commit()
    monkeypatch.setattr(tools.llm_service, "get_llm_for_agent", AsyncMock(return_value=None))
    uri = f"galaris://agent/{owner.id}"
    assert uri in await tools.list_agents(language="fr")
    assert uri in await tools.get_agent_details(owner.id, language="en")
    loaded = await agent_service.get(owner.id)
    assert AgentPublic.model_validate(loaded).model_dump()["resource_uri"] == uri

    ctx = ResourceContext(agent_id=owner.id, runtime="internal")
    profile = json.loads((await files.resource_read(ctx, uri)).content)
    assert profile["personality"] == owner.personality
    assert profile["job_description"] == owner.job_description
    assert profile["resource_uri"] == uri
    assert "write" not in (await files.resource_info(ctx, uri)).capabilities
    owner.job_description = "<p>Nouvelle mission.</p>"
    await db.commit()
    assert json.loads((await files.resource_read(ctx, uri)).content)["job_description"] == owner.job_description

    with pytest.raises(FileNotFoundError):
        await files.resource_read(ResourceContext(agent_id=peer.id, runtime="internal"), uri)
    with pytest.raises(PermissionError):
        await files.resource_write(ctx, uri, b"{}")
    assert await db.scalar(select(func.count()).select_from(MemoryItem)) == 0
    assert await db.scalar(select(func.count()).select_from(DocumentTag)) == 0

    owner.soft_delete()
    await db.commit()
    with pytest.raises(FileNotFoundError):
        await files.resource_read(ctx, uri)
