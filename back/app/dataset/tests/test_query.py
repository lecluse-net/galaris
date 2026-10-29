"""Durable data guarantees: exact arithmetic, bounded output and live authority."""

import json
import pytest
from pydantic import ValidationError

from app.dataset import service
from app.dataset.query import DatasetQuery, execute_query, query_dataset


def test_query_filters_sorts_projects_and_aggregates_all_matches_before_pagination():
    content = '{"contracts":[{"name":"A","active":true,"amount":0.1},{"name":"B","active":true,"amount":0.2},{"name":"C","active":false,"amount":90}]}'
    query = DatasetQuery.model_validate({"path": "/contracts", "filters": [{"path": "/active", "value": True}],
        "sort": [{"path": "/amount", "descending": True}], "fields": ["/name"], "limit": 1,
        "aggregates": [{"name": "total", "op": "sum", "path": "/amount"}, {"name": "count", "op": "count"}]})
    first = execute_query(content, query)
    assert first["items"] == [{"json_pointer": "/contracts/1", "value": {"/name": "B"}}]
    assert first["matched_rows"] == 2 and first["scanned_rows"] == 3
    assert first["aggregates"]["total"] == {"value": "0.3", "present": 2, "missing": 0, "null": 0, "encoding": "decimal"}
    assert first["aggregates"]["count"]["value"] == 2
    assert first["next_offset"] == 1
    second = execute_query(content, query.model_copy(update={"offset": first["next_offset"]}))
    assert second["items"][0]["json_pointer"] == "/contracts/0"
    assert not second["has_more"] and second["aggregates"] == first["aggregates"]


def test_aggregation_preserves_source_decimal_literals_and_reports_missing_values():
    source = '[{"v":0.123456789012345678901234567890123456789},{"v":0.2},{"v":null},{}]'
    query = DatasetQuery.model_validate({"include_rows": False, "aggregates": [
        {"name": "sum", "op": "sum", "path": "/v"}, {"name": "count", "op": "count", "path": "/v"}]})
    result = execute_query(source, query)
    assert result["aggregates"]["sum"]["value"] == "0.323456789012345678901234567890123456789"
    assert result["aggregates"]["sum"]["missing"] == 1
    assert result["aggregates"]["sum"]["null"] == 1
    assert result["aggregates"]["count"]["value"] == 2
    assert not result["items"] and not result["has_more"]


@pytest.mark.parametrize("bad", [True, "12", [], {}])
def test_numeric_aggregates_reject_incompatible_types(bad):
    with pytest.raises(ValueError, match="require numbers"):
        execute_query(json.dumps([{"v": bad}]), DatasetQuery.model_validate({
            "aggregates": [{"name": "sum", "op": "sum", "path": "/v"}]}))


def test_json_pointer_escaping_null_and_missing_are_distinct():
    content = '{"a/b":{"~rows":[{"":null},{},{"":false},{"":0}]}}'
    query = DatasetQuery.model_validate({"path": "/a~1b/~0rows", "filters": [{"path": "/", "op": "exists", "value": True}]})
    assert execute_query(content, query)["matched_rows"] == 3
    query = query.model_copy(update={"filters": []})
    assert execute_query(content, query)["items"][0]["json_pointer"] == "/a~1b/~0rows/0"
    nulls = DatasetQuery.model_validate({"path": query.path, "filters": [{"path": "/", "value": None}]})
    assert execute_query(content, nulls)["matched_rows"] == 1
    numbers = DatasetQuery.model_validate({"path": query.path, "filters": [{"path": "/", "value": 0}]})
    assert execute_query(content, numbers)["items"][0]["json_pointer"] == "/a~1b/~0rows/3"
    with pytest.raises(ValueError, match="does not exist"):
        execute_query(content, DatasetQuery(path="/missing"))


@pytest.mark.parametrize("payload", [
    {"path": "$.rows"}, {"path": "/bad~2key"}, {"limit": 501}, {"limit": True},
    {"filters": [{"path": "/x", "op": "exists", "value": 1}]},
    {"filters": [{"path": "/x", "op": "in", "value": "a"}]},
    {"aggregates": [{"name": "v", "op": "sum"}]},
    {"aggregates": [{"name": "v", "op": "count"}] * 2},
    {"sql": "SELECT 1"},
])
def test_query_rejects_ambiguous_or_unbounded_requests(payload):
    with pytest.raises(ValidationError):
        DatasetQuery.model_validate(payload)


def test_large_rows_require_projection_and_byte_pagination_does_not_drop_rows():
    content = json.dumps([{"key": i, "body": "x" * 40000} for i in range(3)])
    page = execute_query(content, DatasetQuery())
    assert len(page["items"]) == 1 and page["byte_limited"] and page["next_offset"] == 1
    page = execute_query(content, DatasetQuery(offset=page["next_offset"]))
    assert page["items"][0]["json_pointer"] == "/1"
    projected = execute_query(content, DatasetQuery(fields=["/key"]))
    assert len(projected["items"]) == 3 and not projected["has_more"]
    with pytest.raises(ValueError, match="select fewer fields"):
        execute_query(json.dumps([{"large": "x" * 70000}]), DatasetQuery())


def test_empty_numeric_aggregates_and_stable_null_last_sort_are_explicit():
    query = DatasetQuery.model_validate({"sort": [{"path": "/v", "descending": True}],
        "aggregates": [{"name": "avg", "op": "avg", "path": "/v"},
                       {"name": "min", "op": "min", "path": "/v"},
                       {"name": "max", "op": "max", "path": "/v"}]})
    result = execute_query('[{"v":2},{"v":null},{},{"v":1},{"v":2}]', query)
    assert [item["json_pointer"] for item in result["items"]] == ['/0', '/4', '/3', '/1', '/2']
    assert result["aggregates"]["min"]["value"] == '1'
    assert result["aggregates"]["max"]["value"] == '2'
    assert result["aggregates"]["avg"]["precision"] >= 34
    empty = execute_query('[]', query)
    assert empty["aggregates"]["avg"]["value"] is None
    assert not empty["items"] and not empty["has_more"]
    huge = '[{"v":' + '9' * 4000 + '}]'
    aggregates = DatasetQuery.model_validate({"include_rows": False,
        "aggregates": [{"name": str(i), "op": "sum", "path": "/v"} for i in range(20)]})
    with pytest.raises(ValueError, match="fewer aggregates"):
        execute_query(huge, aggregates)


@pytest.mark.asyncio
async def test_query_obeys_live_acl_revision_and_never_writes(db, agents):
    owner, peer = agents
    dataset = await service.create(owner.id, title="Synthetic figures", content='[{"amount":17}]')
    query = DatasetQuery(expected_revision=1)
    with pytest.raises(service.DatasetNotFoundError):
        await query_dataset(dataset.id, peer.id, query)
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=peer.id,
        can_write=False, expected_lock_version=dataset.lock_version)
    result = await query_dataset(dataset.id, peer.id, query)
    assert result["revision"] == 1 and result["items"][0]["value"] == {"amount": 17}
    await service.replace(dataset.id, owner.id, content='[{"amount":18}]', expected_revision=1)
    with pytest.raises(service.DatasetConflictError):
        await query_dataset(dataset.id, peer.id, query)
    await service.set_grant(dataset.id, owner.id, kind="agent", principal=peer.id,
        can_write=None, expected_lock_version=dataset.lock_version)
    with pytest.raises(service.DatasetNotFoundError):
        await query_dataset(dataset.id, peer.id, DatasetQuery())
    assert dataset.revision == 2 and dataset.content == '[{"amount":18}]'


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["internal", "hermes"])
async def test_dataset_query_is_a_typed_read_on_the_file_sharing_tool(runtime):
    from app.tools.mcp_loader import build_galaris_fastmcp
    server = build_galaris_fastmcp(1, runtime=runtime, enabled_tool_codes={"file_sharing"})
    tools = {tool.name: tool for tool in await server.list_tools()}
    schema = tools["dataset_query"].parameters
    assert set(schema["required"]) == {"uri", "query"}
    assert "expected_revision" in str(schema)
    assert "sql" not in schema.get("properties", {})


@pytest.mark.asyncio
async def test_dataset_query_mcp_uses_canonical_uri_and_real_dataset_permissions(db, agents):
    from app.dataset.mcp import dataset_query
    from app.tools.mcp_loader import McpToolContext
    owner, peer = agents
    dataset = await service.create(owner.id, title="Synthetic query", content='[{"value":0.1},{"value":0.2}]')
    query = DatasetQuery.model_validate({"include_rows": False, "expected_revision": 1,
        "aggregates": [{"name": "total", "op": "sum", "path": "/value"}]})
    ctx = McpToolContext(agent_id=owner.id, runtime="internal")
    result = json.loads(await dataset_query(ctx, f"data://{dataset.id}", query))
    assert result["aggregates"]["total"]["value"] == "0.3" and result["revision"] == 1
    with pytest.raises(service.DatasetNotFoundError):
        await dataset_query(McpToolContext(agent_id=peer.id, runtime="internal"), f"data://{dataset.id}", query)
    with pytest.raises(ValueError, match="exact data"):
        await dataset_query(ctx, f"document://{dataset.id}", query)
