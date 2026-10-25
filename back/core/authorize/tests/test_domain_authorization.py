"""Real HTTP boundaries for independently delegable functional domains."""

from uuid import uuid4

import pytest

from core.database import get_db_session
from app.agent.models import Agent, Title
from .test_guard_policy_parameters import actor


async def owned_agent(user_id):
    async with get_db_session() as db:
        title = Title(label="Synthetic domain boundary", gender="X")
        db.add(title)
        await db.flush()
        agent = Agent(
            code=f"domain-{uuid4()}",
            first_name="Synthetic",
            last_name="Domain",
            user_id=user_id,
            title_id=title.id,
            agent_driver="internal",
        )
        db.add(agent)
        await db.flush()
        return agent.id


@pytest.mark.asyncio
async def test_messaging_reception_check_keeps_provider_scope_and_edit_privilege(client):
    for grants, status in [(["MESSAGING_CONFIG_ACCESS"], 403), (["MESSAGING_CONFIG_EDIT"], 200)]:
        headers, _ = await actor(grants)
        response = await client.post('/api/messenger/configuration/test?provider=telegram', headers=headers)
        assert response.status_code == status
        if status == 200:
            assert response.json() == {"provider": "telegram", "ok": False, "connections": []}


@pytest.mark.asyncio
async def test_memory_source_previews_keep_memory_rights_without_files_access(client):
    for code in ["MEMORY_ACCESS", "MEMORY_EDIT", "MEMORY_ADMIN", "FILE_ACCESS", "CONTACT_EDIT"]:
        headers, user_id = await actor([code])
        agent_id = await owned_agent(user_id)
        collection = f"/api/file-share/items/{uuid4()}/resources"
        for suffix in ["", f"/{uuid4()}/content", f"/{uuid4()}/thumbnail"]:
            response = await client.get(collection + suffix, headers=headers, params={"agent_id": agent_id})
            expected = (200 if not suffix else 404) if code.startswith("MEMORY_") else 403
            assert response.status_code == expected, (code, suffix, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,read,edit,former",
    [
        ("/api/contacts", "CONTACT_ACCESS", "CONTACT_EDIT", "MEMORY_ACCESS"),
        ("/api/file-share/indexing", "FILE_INDEX_ACCESS", "FILE_INDEX_RUN", "MEMORY_ACCESS"),
        ("/api/dashboard", "DASHBOARD_ACCESS", "DASHBOARD_ACCESS", "TASK_ACCESS"),
        (
            "/api/conversations/messages",
            "CONVERSATION_ACCESS",
            "CONVERSATION_CONTROL",
            "TASK_ACCESS",
        ),
        (
            "/api/voice/conversations",
            "VOICE_HISTORY_ACCESS",
            "VOICE_HISTORY_CONTROL",
            "TASK_ACCESS",
        ),
        ("/api/llm-calls", "LLM_CALL_ACCESS", "LLM_CALL_CONTROL", "TASK_ACCESS"),
        ("/api/llm-profiles", "LLM_PROFILE_ACCESS", "LLM_PROFILE_EDIT", "PARAMS_ACCESS"),
        ("/api/llm-providers/llms", "LLM_MODEL_ACCESS", "LLM_MODEL_EDIT", "LLM_PROVIDER_ACCESS"),
        (
            "/api/harness-manager/configuration",
            "HARNESS_CONFIG_ACCESS",
            "HARNESS_CONFIG_EDIT",
            "PARAMS_ACCESS",
        ),
        (
            "/api/connections/function-permissions",
            "PERMISSION_ACCESS",
            "PERMISSION_DECIDE",
            "CONNECTION_ACCESS",
        ),
    ],
)
async def test_domain_reader_and_operator_work_without_former_broad_privilege(
    client, path, read, edit, former
):
    for code in set((read, edit)):
        headers, user_id = await actor([code])
        agent_id = await owned_agent(user_id)
        response = await client.get(path, headers=headers, params={"agent_id": agent_id})
        assert response.status_code == 200, (code, path, response.text)
    for codes in (
        [],
        [former],
        ["CONTACT_ACCESS"] if read != "CONTACT_ACCESS" else ["FILE_ACCESS"],
    ):
        headers, user_id = await actor(codes)
        agent_id = await owned_agent(user_id)
        response = await client.get(path, headers=headers, params={"agent_id": agent_id})
        assert response.status_code == 403, (codes, path, response.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "edit,key,value,forbidden",
    [
        ("DREAM_EDIT", "DREAM_ENABLED", "false", "harness.codex.enabled"),
        ("HARNESS_CONFIG_EDIT", "harness.codex.enabled", "false", "DREAM_ENABLED"),
        ("HARNESS_CONFIG_EDIT", "PYDANTIC_AI_BINARY_INPUT_MAX_BYTES", "20000000", "DREAM_ENABLED"),
        ("LANGUAGE_CONFIG_EDIT", "LOCALIZATION", "Synthetic region", "DREAM_ENABLED"),
    ],
)
async def test_generic_params_cannot_bypass_a_domain_policy(client, edit, key, value, forbidden):
    headers, _ = await actor([edit])
    listed = await client.get("/api/params", headers=headers)
    assert listed.status_code == 200
    names = {row["name"] for row in listed.json()["params"]}
    assert key in names and forbidden not in names
    saved = await client.put(f"/api/params/{key}", headers=headers, json={"value": value})
    assert saved.status_code == 200, saved.text
    denied = await client.put(f"/api/params/{forbidden}", headers=headers, json={"value": "true"})
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_dream_domain_does_not_grant_global_management(client):
    headers, _ = await actor(["DREAM_ACCESS"])
    assert (await client.get("/api/dream/runtime", headers=headers)).status_code == 403
    headers, _ = await actor(["DREAM_ACCESS", "AGENT_MANAGE_ALL"])
    assert (await client.get("/api/dream/runtime", headers=headers)).status_code == 200
    headers, _ = await actor(["TASK_ACCESS", "AGENT_MANAGE_ALL"])
    assert (await client.get("/api/dream/runtime", headers=headers)).status_code == 403
    headers, _ = await actor(["DREAM_EDIT", "AGENT_MANAGE_ALL"])
    assert (await client.get("/api/dream/runtime", headers=headers)).status_code == 403
    headers, _ = await actor(["DREAM_CONFIG_ACCESS", "AGENT_MANAGE_ALL"])
    listed = await client.get("/api/params", headers=headers)
    assert any(param["name"] == "DREAM_ENABLED" for param in listed.json()["params"])
    assert (await client.get("/api/dream/runtime", headers=headers)).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind,code",
    [
        ("document", "DOCUMENT_ACCESS"),
        ("dataset", "DATASET_READ"),
        ("task", "TASK_ACCESS"),
        ("message", "CHAT_ACCESS"),
        ("conversation_round", "CONVERSATION_ACCESS"),
        ("voice_session", "VOICE_HISTORY_ACCESS"),
    ],
)
async def test_topic_provenance_uses_its_subject_domain(client, kind, code):
    params = {"topic_id": str(uuid4()), "subject_id": str(uuid4()), "subject_kind": kind}
    headers, _ = await actor([code])
    # An absent subject reaches the scoped lookup with the right domain grant.
    allowed = await client.get("/api/dream/topic-assignment", headers=headers, params=params)
    assert allowed.status_code == 404, allowed.text
    headers, _ = await actor(["CONTACT_ACCESS"])
    assert (
        await client.get("/api/dream/topic-assignment", headers=headers, params=params)
    ).status_code == 403


@pytest.mark.asyncio
async def test_assignment_catalogues_are_minimal_and_do_not_grant_role_or_user_administration(
    client,
):
    headers, _ = await actor(["MANAGE_ASSIGNMENT"])
    roles = await client.get("/api/authorize/role-options", headers=headers)
    assert roles.status_code == 200
    assert all(set(role) == {"id", "code", "display_name"} for role in roles.json())
    users = await client.get(
        "/api/authorize/assignment-user-options", headers=headers, params={"q": "policy-"}
    )
    assert users.status_code == 200 and users.json()
    assert all(set(user) == {"id", "email", "display_name"} for user in users.json())
    assert (await client.get("/api/authorize/roles", headers=headers)).status_code == 403
    assert (
        await client.post("/api/authorize/roles", headers=headers, json={"code": "forbidden"})
    ).status_code == 403


@pytest.mark.asyncio
async def test_file_browser_uses_source_domain_and_never_client_policy_fields(client):
    for code, allowed_scheme, forbidden_scheme in [
        ("FILE_EDIT", "console", "document"),
        ("DOCUMENT_EDIT", "document", "console"),
        ("DATASET_EDIT", "data", "console"),
    ]:
        headers, user_id = await actor([code])
        agent_id = await owned_agent(user_id)
        # A missing authorized resource reaches its provider (404/422); a
        # neighboring domain is denied before provider access (403).
        uri = f"{allowed_scheme}://{uuid4()}"
        allowed = await client.get(
            "/api/file-share/browser/info",
            headers=headers,
            params={"agent_id": agent_id, "uri": uri},
        )
        assert allowed.status_code in {404, 422}, allowed.text
        denied = await client.get(
            "/api/file-share/browser/info",
            headers=headers,
            params={
                "agent_id": agent_id,
                "uri": f"{forbidden_scheme}://{uuid4()}",
                "mutation": False,
            },
        )
        assert denied.status_code == 403

    headers, user_id = await actor(["FILE_ACCESS"])
    agent_id = await owned_agent(user_id)
    denied = await client.delete(
        "/api/file-share/browser/entry",
        headers=headers,
        params={"agent_id": agent_id, "uri": "console://Synthetic.txt", "mutation": "false"},
    )
    assert denied.status_code == 403

    document_headers, user_id = await actor(["DOCUMENT_EDIT"])
    agent_id = await owned_agent(user_id)
    denied = await client.request(
        "GET",
        "/api/file-share/browser/info",
        headers=document_headers,
        params={"agent_id": agent_id, "uri": "console://Synthetic.txt"},
        json={"uri": f"document://{uuid4()}", "agent_id": agent_id},
    )
    assert denied.status_code == 403


@pytest.mark.asyncio
async def test_permission_revocation_cannot_enable_or_inherit_an_allow_rule(client):
    from app.tools import ToolModel
    from app.connection import Connection

    headers, user_id = await actor(["PERMISSION_REVOKE"])
    agent_id = await owned_agent(user_id)
    async with get_db_session() as db:
        tool = ToolModel(code=f"synthetic-policy-{uuid4()}", label="Synthetic policy Tool")
        db.add(tool)
        await db.flush()
        connection = Connection(agent_id=agent_id, tool_id=tool.id, active=True)
        db.add(connection)
        await db.flush()
        connection_id = connection.id
    options = await client.get("/api/connections/permission-options", headers=headers)
    assert options.status_code == 200, options.text
    assert options.json()[0]["id"] == connection_id
    assert "params" not in options.json()[0]
    assert (await client.get("/api/connections", headers=headers)).status_code == 403
    endpoint = f"/api/connections/{connection_id}/functions/synthetic_action"
    for state in ("enabled", "default"):
        assert (
            await client.put(endpoint, headers=headers, json={"state": state})
        ).status_code == 403
    blocked = await client.put(endpoint, headers=headers, json={"state": "disabled"})
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["effective_state"] == "disabled"


@pytest.mark.asyncio
async def test_task_settings_read_only_pipeline_eligibility_without_harness_configuration(client):
    headers, _ = await actor(["TASK_CONFIG_ACCESS"])
    response = await client.get("/api/harnesses/pipeline-options", headers=headers)
    assert response.status_code == 200 and response.json()
    assert all(
        set(option) == {"provider_code", "label", "pipeline_policy"} for option in response.json()
    )
    assert (
        await client.get("/api/harnesses/execution-configurations", headers=headers)
    ).status_code == 403
