"""Human avatar generation uses the default profile and preserves concurrent edits."""

import io
import json
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from PIL import Image
from sqlalchemy import delete, select

from app.agent.models import Agent, Title
from app.image import image_service
from app.llm import LLM, LLMProvider, LlmProfile, profile_service
from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel


@pytest_asyncio.fixture
async def client(committed_database, monkeypatch):
    """Use real independent transactions so failed requests cannot undo concurrent edits."""
    from httpx import ASGITransport, AsyncClient
    from core.database import middleware
    from app.llm import llm_call_service
    from main import app

    monkeypatch.setattr(middleware, "AsyncSessionLocal", committed_database)
    monkeypatch.setattr(llm_call_service, "AsyncSessionLocal", committed_database)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://localhost") as http:
        yield http


def image_bytes(color="blue"):
    output = io.BytesIO()
    Image.new("RGB", (1024, 1024), color).save(output, "PNG")
    return output.getvalue()


@pytest_asyncio.fixture
async def portrait_configuration(client, monkeypatch):
    from core import settings

    monkeypatch.setattr(settings, "APP_HOST", "http://localhost")
    credentials = {"email": f"portrait-{uuid4().hex}@example.com", "password": "Synthetic-avatar-password-42!"}
    registered = await client.post("/api/auth/register", json=credentials)
    assert registered.status_code == 201, registered.text
    async with get_db_session() as db:
        user = await db.scalar(select(UserModel).where(UserModel.email == credentials["email"]))
        other = UserModel(email=f"other-{uuid4().hex}@example.test", hashed_password="unused", is_active=True)
        privileges = (await db.scalars(select(Privilege).where(Privilege.code.in_(["AGENT_EDIT", "AGENT_ACCESS"])))).all()
        role = Role(code=f"portrait-manager-{uuid4().hex}", privileges=list(privileges))
        title = Title(label="Synthetic title", gender="F")
        provider = LLMProvider(name=f"Synthetic provider {uuid4().hex}", base_url="https://image.example.test", is_active=True)
        db.add_all([other, role, title, provider])
        await db.flush()
        await db.execute(delete(Assignment).where(Assignment.user_id == user.id))
        db.add(Assignment(user_id=user.id, role_id=role.id, is_default=True))
        model = LLM(llm_provider_id=provider.id, code=f"default-image-{uuid4().hex}", llm_name="synthetic-image", label="Synthetic image", output_image=True,
                    primary_capability="image_generation", service_capabilities=["image_generation"])
        db.add(model)
        await db.flush()
        default = LlmProfile(code=f"default-{uuid4().hex}", label="Default portrait profile", image_llm_id=model.id)
        custom = LlmProfile(code=f"custom-{uuid4().hex}", label="Agent profile without images")
        db.add_all([default, custom])
        await db.flush()
        await profile_service.set_current_profile_id(default.id)
        agent = Agent(user_id=user.id, title_id=title.id, profile_id=custom.id, code=f"portrait-{uuid4().hex}",
                      first_name="Lyra", last_name="Synthetic", personality="<p>Patient <b>observer</b>.</p>",
                      job_title="Astronomer", job_description="<p>Study distant galaxies.</p>")
        outsider = Agent(user_id=other.id, title_id=title.id, code=f"outside-{uuid4().hex}", first_name="Other", last_name="Synthetic")
        db.add_all([agent, outsider])
        await db.flush()
        data = {"agent_id": agent.id, "outsider_id": outsider.id, "user_id": user.id, "other_id": other.id,
                "model_id": model.id, "model_code": model.code, "provider_id": provider.id, "profile_id": default.id}
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200, login.text
    data["headers"] = {"Authorization": f"Bearer {login.json()['access_token']}"}
    return data


@pytest.mark.asyncio
async def test_http_generation_uses_default_profile_and_registers_compact_portrait(client, portrait_configuration, monkeypatch):
    config = portrait_configuration
    provider = AsyncMock(return_value=(image_bytes(), "image/png"))
    monkeypatch.setattr(image_service, "generate_image_native", provider)
    availability = await client.get("/api/agents/avatar-generation", headers=config["headers"])
    assert availability.status_code == 200 and availability.json() == {"available": True}
    response = await client.post(f"/api/agents/{config['agent_id']}/avatar/generate", headers=config["headers"])
    assert response.status_code == 200, response.text
    assert response.json()["avatar_revision"] == 1
    args, options = provider.call_args
    assert args[0] == config["model_code"]
    assert options["width"] == options["height"] == 1024
    profile = json.loads(args[1].split("\n")[1])
    assert profile == {"first_name": "Lyra", "last_name": "Synthetic", "gender": "F", "personality": "Patient observer.",
                       "job_title": "Astronomer", "job_description": "Study distant galaxies."}
    avatar = await client.get(f"/api/agents/{config['agent_id']}/avatar", headers=config["headers"])
    with Image.open(io.BytesIO(avatar.content)) as stored:
        assert stored.format == "JPEG" and stored.size == (500, 500)
    provider.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("unavailable", ["missing", "inactive", "credentials", "not_image"])
async def test_http_generation_hides_and_rejects_unavailable_configuration(client, portrait_configuration, monkeypatch, unavailable):
    config = portrait_configuration
    provider = AsyncMock()
    monkeypatch.setattr(image_service, "generate_image_native", provider)
    async with get_db_session() as db:
        if unavailable == "missing":
            (await db.get(LlmProfile, config["profile_id"])).image_llm_id = None
        elif unavailable == "inactive":
            (await db.get(LLMProvider, config["provider_id"])).is_active = False
        elif unavailable == "not_image":
            (await db.get(LLM, config["model_id"])).output_image = False
        else:
            from bridge.openrouter import PROFILE
            from app.llm.provider_facade import register_provider
            register_provider(PROFILE)
            seeded = await db.scalar(select(LLMProvider).where(LLMProvider.catalog_code == "openrouter"))
            if seeded:
                seeded.catalog_code = None
                await db.flush()
            (await db.get(LLMProvider, config["provider_id"])).catalog_code = "openrouter"
    assert (await client.get("/api/agents/avatar-generation", headers=config["headers"])).json() == {"available": False}
    response = await client.post(f"/api/agents/{config['agent_id']}/avatar/generate", headers=config["headers"])
    assert response.status_code == 409, response.text
    provider.assert_not_awaited()


@pytest.mark.asyncio
async def test_http_generation_requires_authorized_manager(client, portrait_configuration, monkeypatch):
    config = portrait_configuration
    provider = AsyncMock()
    monkeypatch.setattr(image_service, "generate_image_native", provider)
    assert (await client.get("/api/agents/avatar-generation")).status_code in {401, 403}
    assert (await client.post(f"/api/agents/{config['agent_id']}/avatar/generate")).status_code in {401, 403}
    assert (await client.post(f"/api/agents/{config['outsider_id']}/avatar/generate", headers=config["headers"])).status_code == 403
    async with get_db_session() as db:
        role = Role(code=f"read-only-{uuid4().hex}", privileges=list((await db.scalars(select(Privilege).where(Privilege.code == "AGENT_ACCESS"))).all()))
        db.add(role)
        await db.flush()
        await db.execute(delete(Assignment).where(Assignment.user_id == config["user_id"]))
        db.add(Assignment(user_id=config["user_id"], role_id=role.id, is_default=True))
    assert (await client.get("/api/agents/avatar-generation", headers=config["headers"])).status_code == 403
    assert (await client.post(f"/api/agents/{config['agent_id']}/avatar/generate", headers=config["headers"])).status_code == 403
    provider.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("change,status", [("profile", 409), ("avatar", 409), ("owner", 403), ("permission", 403), ("invalid", 502), ("provider", 502), ("provider_http", 502)])
async def test_http_generation_preserves_existing_avatar_on_failure_or_concurrent_change(client, portrait_configuration, monkeypatch, change, status):
    config = portrait_configuration
    from app.agent import agent_service
    async with get_db_session():
        await agent_service.update_avatar(config["agent_id"], image_bytes("red"))

    async def generate(*args, **kwargs):
        async with get_db_session() as db:
            agent = await db.get(Agent, config["agent_id"])
            if change == "profile":
                agent.job_description = "<p>A changed mission.</p>"
            elif change == "avatar":
                await agent_service.update_avatar(agent.id, image_bytes("green"))
            elif change == "owner":
                agent.user_id = config["other_id"]
            elif change == "permission":
                await db.execute(delete(Assignment).where(Assignment.user_id == config["user_id"]))
        if change == "provider":
            raise RuntimeError("Synthetic provider secret must stay private")
        if change == "provider_http":
            from app.llm import ImageGenerationProviderError
            raise ImageGenerationProviderError("synthetic-image", 400, "Synthetic provider secret must stay private")
        return (b"invalid" if change == "invalid" else image_bytes()), "image/png"

    monkeypatch.setattr(image_service, "generate_image_native", generate)
    response = await client.post(f"/api/agents/{config['agent_id']}/avatar/generate", headers=config["headers"])
    assert response.status_code == status, response.text
    assert "secret" not in response.text
    if change == "provider_http":
        assert "synthetic-image" in response.json()["detail"]
        assert "400" in response.json()["detail"]
    async with get_db_session() as db:
        agent = await db.get(Agent, config["agent_id"])
        assert agent.avatar_revision == (2 if change == "avatar" else 1)
        with Image.open(io.BytesIO(agent.avatar)) as avatar:
            rgb = avatar.getpixel((250, 250))
            assert rgb[1] > 100 if change == "avatar" else rgb[0] > 250
