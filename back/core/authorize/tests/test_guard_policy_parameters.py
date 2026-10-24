"""HTTP clients cannot replace the server's authorization policy."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from core.authorize import Assignment, Privilege, Role
from core.database import get_db_session
from core.user import UserModel
from core.user.auth_service import create_access_token


async def actor(codes: list[str]) -> tuple[dict[str, str], int]:
    async with get_db_session() as db:
        user = UserModel(
            email=f"policy-{uuid4()}@example.com", hashed_password="unused", is_active=True
        )
        grants = list(await db.scalars(select(Privilege).where(Privilege.code.in_(codes))))
        role = Role(code=f"policy-role-{uuid4()}", privileges=grants)
        db.add_all([user, role])
        await db.flush()
        db.add(Assignment(user_id=user.id, role_id=role.id))
        token = create_access_token({"sub": user.email, "user_id": user.id, "role_id": role.id})
        return {"Authorization": f"Bearer {token}"}, user.id


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["json", "query", "form"])
async def test_client_data_cannot_weaken_the_server_privilege_conjunction(client, transport):
    headers, _ = await actor(["TEAM_EDIT"])
    payload = {"name": "Synthetic policy team", "required_privileges": ["TEAM_EDIT"]}
    if transport == "json":
        response = await client.post("/api/teams", headers=headers, json=payload)
    elif transport == "query":
        response = await client.post(
            "/api/teams",
            headers=headers,
            params={"required_privileges": "TEAM_EDIT"},
            json={"name": payload["name"]},
        )
    else:
        response = await client.post("/api/teams", headers=headers, data=payload)
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_server_conjunction_keeps_legitimate_access_despite_client_policy_fields(client):
    headers, _ = await actor(["TEAM_ACCESS", "TEAM_EDIT"])
    response = await client.post(
        "/api/teams",
        headers=headers,
        json={"name": "Synthetic authorized team", "required_privileges": ["MISSING_PRIVILEGE"]},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
@pytest.mark.parametrize("injected", ["fallback", "owner", "path"])
async def test_client_cannot_change_ownership_policy_or_path_identity(client, injected):
    headers, owner = await actor([])
    _, other = await actor([])
    params = {
        "fallback": {"fallback_privilege": "user"},
        "owner": {"owner_param": "forged_owner", "forged_owner": str(owner)},
        "path": {"user_id": str(owner)},
    }[injected]
    response = await client.get(
        f"/api/authorize/users/{other}/assignments", headers=headers, params=params
    )
    assert response.status_code == 403
    assert (
        await client.get(f"/api/authorize/users/{owner}/assignments", headers=headers)
    ).status_code == 200


@pytest.mark.asyncio
async def test_mcp_credentials_still_require_the_dedicated_privilege(client):
    from app.agent.models import Agent, Title

    headers, owner = await actor(["AGENT_EDIT"])
    async with get_db_session() as db:
        title = Title(label="Synthetic policy agent", gender="X")
        db.add(title)
        await db.flush()
        agent = Agent(
            code=f"policy-{uuid4()}",
            first_name="Synthetic",
            last_name="Policy",
            title_id=title.id,
            user_id=owner,
            agent_driver="internal",
        )
        db.add(agent)
        await db.flush()
        agent_id = agent.id
    response = await client.post(
        f"/api/agents/{agent_id}/mcp-tokens",
        headers=headers,
        json={"label": "Synthetic denied credential", "required_privileges": ["AGENT_EDIT"]},
    )
    assert response.status_code == 403
