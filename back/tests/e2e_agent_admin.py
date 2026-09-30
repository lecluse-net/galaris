"""Synthetic AgentAdmin browser fixtures, installed only by tests.e2e_app."""

import io
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException
from fastmcp import Client
from PIL import Image
from sqlalchemy import select

from app.agent import Agent, Title
from app.connection import Connection
from app.llm import LLM, LLMProvider, LlmProfile
from app.tools import build_agent_galaris_fastmcp, sync_integrated_tool_connections, ToolModel
from core.database import get_db_session

router = APIRouter(prefix="/api/__test/agent-admin")


async def portrait_provider(prompt: str, **kwargs: Any) -> tuple[bytes, str]:
    output = io.BytesIO()
    Image.new("RGB", (1024, 640), "green" if "green backdrop" in prompt else "blue").save(output, "PNG")
    return output.getvalue(), "image/png"


@router.post("/{caller_id}/setup")
async def setup(caller_id: int) -> dict[str, int]:
    async with get_db_session() as db:
        caller = await db.get(Agent, caller_id)
        if caller is None or not caller.code.startswith("browser-"):
            raise HTTPException(404, "Synthetic browser agent not found")
        await sync_integrated_tool_connections(caller_id)
        tool = await db.scalar(select(ToolModel).where(ToolModel.code == "agent_admin"))
        connection = await db.scalar(select(Connection).where(Connection.agent_id == caller_id, Connection.tool_id == tool.id))
        connection.active = True
        provider = LLMProvider(name=f"Synthetic portrait {uuid4().hex}", base_url="https://portrait.example.test")
        db.add(provider)
        await db.flush()
        model = LLM(llm_provider_id=provider.id, code=f"portrait-{uuid4().hex}", llm_name="portrait",
                    label="Synthetic portraits", primary_capability="image_generation", service_capabilities=["image_generation"], output_image=True)
        db.add(model)
        await db.flush()
        profile = LlmProfile(label="Synthetic portraits", image_llm_id=model.id)
        db.add(profile)
        await db.flush()
        caller.profile_id = profile.id
        await db.commit()
        return {"user_id": caller.user_id, "title_id": caller.title_id}


@router.post("/{caller_id}/call/{function}")
async def call(caller_id: int, function: str, arguments: dict[str, Any]) -> dict[str, Any]:
    async with get_db_session():
        server = await build_agent_galaris_fastmcp(caller_id, allowed_tool_names={function})
    async with Client(server) as client:
        result = await client.call_tool(function, arguments, raise_on_error=False)
        return {"is_error": result.is_error, "data": result.data}


@router.post("/{caller_id}/revoke")
async def revoke(caller_id: int) -> dict[str, bool]:
    async with get_db_session() as db:
        connection = await db.scalar(select(Connection).join(ToolModel).where(
            Connection.agent_id == caller_id, ToolModel.code == "agent_admin"))
        connection.active = False
        await db.commit()
        return {"revoked": True}
