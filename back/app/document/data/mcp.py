"""Dataset-owned deterministic data operations exposed through File Sharing."""

import json
from uuid import UUID

from app.tools import McpToolContext, mcp_tool

from .query import DatasetQuery, query_dataset


@mcp_tool("file_sharing", name="dataset_query", approval="enabled",
    approval_reason="Governed bounded read without a new sensitive effect",
    effect_policy="read", concurrency_policy="safe",
    description=(
        "Query one accessible data:// UUID without downloading its complete JSON. "
        "Use RFC 6901 JSON pointers, empty for root; an array at query.path becomes rows. "
        "Filter with AND, project fields, sort, paginate and aggregate all matching rows. "
        "Use expected_revision from discovery to reject changed data. Numeric aggregates return "
        "decimal strings with missing/null counts; incompatible numeric types are errors. "
        "No expressions, SQL, inferred unit conversion or date parsing. ISO date strings can be "
        "ordered only when they share the same format and timezone. Read-only; does not grant access."
    ))
async def dataset_query(ctx: McpToolContext, uri: str, query: DatasetQuery) -> str:
    if not uri.startswith("data://") or "/" in uri.removeprefix("data://"):
        raise ValueError("Use the exact data://<uuid> returned by discovery")
    result = await query_dataset(UUID(uri.removeprefix("data://")), ctx.agent_id, query)
    return json.dumps(result, ensure_ascii=False, allow_nan=False)
