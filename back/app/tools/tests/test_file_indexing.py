"""Administrator indexing preferences preserve integrated definitions and provider limits."""

import pytest
from sqlalchemy import select

from app.tools import tool_service
from app.tools.dbadmin import datasets, _reconcile_standard_params
from app.tools.contracts import FILE_INDEXING_PARAM
from app.tools.schemas import ToolGlobalParamsUpdate
from app.tools.models import Tool
from app.tools.projections import to_public
from core.dbadmin import reconcile_dataset


def setting(value, forced=False):
    return ToolGlobalParamsUpdate.model_validate({"params": {FILE_INDEXING_PARAM: {"value": value, "forced": forced}}})


@pytest.mark.asyncio
async def test_console_indexing_preference_survives_integrated_sync(db):
    console = await db.scalar(select(Tool).where(Tool.code == "console"))
    assert to_public(console).global_params[FILE_INDEXING_PARAM].value == "known_uris"
    original_config = dict(console.file_share_config)
    changed = await tool_service.update_global_params(console.id, setting("known_uris"))
    assert to_public(changed).global_params[FILE_INDEXING_PARAM].value == "known_uris"
    assert [option.value for option in to_public(changed).connection_schema.params[FILE_INDEXING_PARAM].options] == ["excluded", "known_uris"]
    with pytest.raises(ValueError):
        await tool_service.update_global_params(console.id, setting("recursive"))
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await db.refresh(console)
    assert to_public(console).global_params[FILE_INDEXING_PARAM].value == "known_uris"
    assert console.file_share_config == original_config
    await tool_service.update_global_params(console.id, setting("excluded"))
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await _reconcile_standard_params(db)
    await db.refresh(console)
    assert to_public(console).global_params[FILE_INDEXING_PARAM].value == "excluded"


@pytest.mark.asyncio
@pytest.mark.parametrize("config,allowed", [
    (None, []),
    ({"service": "mail", "base_url": ""}, []),
    ({"service": "affine", "base_url": ""}, ["excluded", "known_uris"]),
    ({"service": "grav", "base_url": ""}, ["excluded", "known_uris"]),
    ({"service": "nextcloud", "base_url": ""}, ["excluded", "known_uris", "recursive"]),
])
async def test_provider_limits_apply_to_custom_tool_codes(db, config, allowed):
    tool = Tool(code="synthetic-indexed-files", label="Synthetic files",
                file_share_config=config, messenger_config={"service": "matrix"})
    db.add(tool)
    await db.flush()
    definition = to_public(tool).connection_schema.params.get(FILE_INDEXING_PARAM)
    assert ([option.value for option in definition.options] if definition else []) == allowed
    if definition:
        assert definition.default == "known_uris"
    for mode in ("known_uris", "recursive"):
        if mode in allowed:
            await tool_service.update_global_params(tool.id, setting(mode))
            assert to_public(tool).global_params[FILE_INDEXING_PARAM].value == mode
        else:
            with pytest.raises(ValueError):
                await tool_service.update_global_params(tool.id, setting(mode))


@pytest.mark.asyncio
async def test_missing_tool_is_not_created_by_preference(db):
    assert await tool_service.update_global_params(999999999, setting("excluded")) is None


@pytest.mark.asyncio
async def test_http_indexing_preference_requires_tool_management(client):
    credentials = {"email": "indexing-admin@example.com", "password": "synthetic-indexing-password"}
    assert (await client.post("/api/auth/register", json=credentials)).status_code == 201
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    listed = await client.get("/api/tools", headers=headers)
    assert listed.status_code == 200
    console = next(tool for tool in listed.json() if tool["code"] == "console")
    path = f"/api/tools/{console['id']}/global-params"
    changed = await client.put(path, headers=headers, json=setting("known_uris").model_dump())
    assert changed.status_code == 200
    assert changed.json()["params"][FILE_INDEXING_PARAM]["value"] == "known_uris"
    assert (await client.put(path, headers=headers, json=setting("recursive").model_dump())).status_code == 422
    assert (await client.put(path, json=setting("excluded").model_dump())).status_code == 401
    reader = {"email": "indexing-reader@example.com", "password": "synthetic-reader-password"}
    assert (await client.post("/api/auth/users", headers=headers, json=reader)).status_code == 201
    login = await client.post("/api/auth/login-json", json=reader)
    assert login.status_code == 200
    reader_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert (await client.put(path, headers=reader_headers, json=setting("excluded").model_dump())).status_code == 403
    # Switching browser accounts revokes the previous web session; open a new admin session.
    login = await client.post("/api/auth/login-json", json=credentials)
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    reopened = await client.get(f"/api/tools/{console['id']}", headers=headers)
    assert reopened.json()["global_params"][FILE_INDEXING_PARAM]["value"] == "known_uris"


@pytest.mark.asyncio
async def test_standard_indexing_local_global_forced_and_default_resolution(db):
    from app.agent import Agent
    from app.agent.models import Title
    from app.connection import Connection
    from app.connection import connection_service
    from app.connection.facade import effective_param_value_expression
    from app.file_share.file_share_service import effective_file_indexing_mode

    title = Title(label="Synthetic indexing fixture", gender="X")
    db.add(title)
    await db.flush()
    agents = [Agent(title_id=title.id, code=f"indexing-agent-{i}", first_name="Synthetic",
                    last_name=f"Indexing {i}", agent_driver="internal") for i in range(2)]
    db.add_all(agents)
    await db.flush()
    tool = await db.scalar(select(Tool).where(Tool.code == "console"))
    local, inherited = [Connection(agent_id=agent.id, tool_id=tool.id) for agent in agents]
    db.add_all([local, inherited])
    await db.flush()
    expression = effective_param_value_expression(Tool.global_params, Tool.connection_schema, Connection.id, FILE_INDEXING_PARAM)

    async def values():
        return dict((await db.execute(select(Connection.id, expression).join(Tool).where(Connection.tool_id == tool.id))).all())

    await connection_service.set_params_bulk(local.id, {FILE_INDEXING_PARAM: "excluded"})
    assert await values() == {local.id: "excluded", inherited.id: "known_uris"}
    assert (await connection_service.get_params_as_dict(local))[1][FILE_INDEXING_PARAM] == "excluded"
    assert (await connection_service.get_params_as_dict(inherited))[1][FILE_INDEXING_PARAM] == "known_uris"
    assert await effective_file_indexing_mode(agents[0].id, "console") == "excluded"
    assert await effective_file_indexing_mode(agents[1].id, "console") == "known_uris"
    with pytest.raises(ValueError):
        await connection_service.set_params_bulk(local.id, {FILE_INDEXING_PARAM: "recursive"})
    await tool_service.update_global_params(tool.id, setting("known_uris", forced=True))
    assert set((await values()).values()) == {"known_uris"}
    assert (await connection_service.get_params_as_dict(local))[1][FILE_INDEXING_PARAM] == "known_uris"
    assert await effective_file_indexing_mode(agents[0].id, "console") == "known_uris"
    local.active = False
    await db.flush()
    assert await effective_file_indexing_mode(agents[0].id, "console") == "excluded"
    local.active = True
    await db.flush()
    with pytest.raises(ValueError):
        await connection_service.set_params_bulk(local.id, {FILE_INDEXING_PARAM: "excluded"})
    await tool_service.update_global_params(tool.id, ToolGlobalParamsUpdate.model_validate({"params": {FILE_INDEXING_PARAM: {"clear": True}}}))
    await connection_service.set_params_bulk(local.id, {FILE_INDEXING_PARAM: None})
    assert set((await values()).values()) == {"known_uris"}


@pytest.mark.asyncio
async def test_legacy_preferences_backfill_once_without_overwriting_standard_values(db):
    console = await db.scalar(select(Tool).where(Tool.code == "console"))
    console.file_indexing_mode = "known_uris"
    console.global_params = {name: entry for name, entry in console.global_params.items() if name != FILE_INDEXING_PARAM}
    custom = Tool(code="synthetic-legacy-share", label="Synthetic legacy share",
        file_share_config={"service": "nextcloud", "base_url": ""}, file_indexing_mode="recursive",
        connection_schema={"params": {"note": {"type": "string", "label": "Custom note"}}},
        global_params={"note": {"value": "Preserved value", "forced": True}})
    db.add(custom)
    await db.flush()
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    await _reconcile_standard_params(db)
    assert console.global_params[FILE_INDEXING_PARAM]["value"] == "known_uris"
    assert custom.global_params[FILE_INDEXING_PARAM]["value"] == "recursive"
    assert custom.global_params["note"] == {"value": "Preserved value", "forced": True}
    assert custom.connection_schema["params"]["note"]["label"] == "Custom note"
    await tool_service.update_global_params(console.id, setting("excluded"))
    await tool_service.update_global_params(custom.id, setting("known_uris", forced=True))
    await _reconcile_standard_params(db)
    for dataset in datasets():
        await reconcile_dataset(db, dataset)
    assert console.global_params[FILE_INDEXING_PARAM]["value"] == "excluded"
    assert custom.global_params[FILE_INDEXING_PARAM] == {"value": "known_uris", "forced": True}
