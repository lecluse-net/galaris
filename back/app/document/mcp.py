"""Domain operations for shared Documents."""

import json
from html import escape
from typing import Annotated, Any, Literal
from urllib.parse import quote
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.agent import EffectDescriptorV1
from app.services import McpToolContext, mcp_tool
from app.services.contracts import ToolArgumentsRejectedError, ToolCallRejectedError

from . import item_sharing, resource_service
from .formats import DocumentRevisionRegion
from .tool_access import require_document_tool_scope

DocumentUri = Annotated[str, Field(pattern=r"^document://[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$")]
RevisionNumber = Annotated[int, Field(ge=1)]
ChartKind = Literal["bar", "line", "pie"]


class ChartRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
    value: Annotated[float, Field(strict=True, ge=-1e15, le=1e15, allow_inf_nan=False)]


@mcp_tool("document", name="document_chart", approval="enabled", conversation_policy="short",
    approval_reason="Prepare an editable chart from supplied values",
    description="Use this for charts in Text documents and mind map nodes. Pass chart_type (bar, line or pie), an optional title, and 1–20 rows with a label and numeric value. The returned html is a native editable chart rendered by Galaris with ECharts. Insert it verbatim via the existing document or mind map writing tool. This call does not save anything.",
    effect_policy="read", concurrency_policy="safe")
async def document_chart(ctx: McpToolContext, chart_type: ChartKind,
    rows: Annotated[list[ChartRow], Field(min_length=1, max_length=20)],
    title: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = "") -> str:
    if chart_type == "pie" and (any(row.value < 0 for row in rows) or not any(row.value > 0 for row in rows)):
        raise ToolArgumentsRejectedError("Pie values must be nonnegative, with at least one positive value.")
    chart = {"version": 1, "type": chart_type, "title": title,
        "rows": [row.model_dump(mode="json") for row in rows]}
    try:
        encoded = quote(json.dumps(chart, ensure_ascii=False, separators=(",", ":")), safe="")
    except UnicodeEncodeError as exc:
        raise ToolArgumentsRejectedError("Chart labels and title must be valid Unicode.") from exc
    values = " · ".join(f"{row.label} {row.value}" for row in rows)
    caption = f"{title} · {values}" if title else values
    fragment = f'<figure data-galaris-chart="{encoded}"><figcaption>{escape(caption)}</figcaption></figure>'
    return json.dumps({"html": fragment}, ensure_ascii=True)


def _identity(value: str) -> UUID:
    return UUID(value.strip().removeprefix("document://"))


@mcp_tool("document", name="document_revision_list", approval="enabled", conversation_policy="short",
    approval_reason="Read saved content revision history for an accessible document",
    description="List saved document content versions, newest first. Use their exact revision numbers with file_read or document_revision_compare.",
    effect_descriptor=EffectDescriptorV1(capability="file.read", kind="read", target_arguments=("document_id",),
        idempotence="read_only", receipt="resource"), effect_policy="read", concurrency_policy="safe")
async def document_revision_list(ctx: McpToolContext, document_id: DocumentUri,
    offset: Annotated[int, Field(ge=0)] = 0, limit: Annotated[int, Field(ge=1, le=50)] = 20) -> str:
    identity = _identity(document_id)
    await require_document_tool_scope(ctx.agent_id, identity)
    page = await resource_service.list_document_content_revisions(identity, actor_agent_id=ctx.agent_id,
        offset=offset, limit=limit)
    return json.dumps({"uri": f"document://{identity}", **page.model_dump(mode="json", exclude={
        "items": {"__all__": {"author_user_id", "author_agent_id", "task_id"}},
    })}, ensure_ascii=False)


@mcp_tool("document", name="document_revision_compare", approval="enabled", conversation_policy="short",
    approval_reason="Read and compare two saved content revisions of an accessible document",
    description="Compare two saved document revisions. Supported drawing formats report pixel changes, optionally restricted to a rectangle in source pixels. A content_hash comparison only reports that bytes differ.",
    effect_descriptor=EffectDescriptorV1(capability="file.read", kind="read", target_arguments=("document_id",),
        idempotence="read_only", receipt="resource"), effect_policy="read", concurrency_policy="safe")
async def document_revision_compare(ctx: McpToolContext, document_id: DocumentUri,
    before_revision: RevisionNumber, after_revision: RevisionNumber, region: DocumentRevisionRegion | None = None) -> str:
    identity = _identity(document_id)
    await require_document_tool_scope(ctx.agent_id, identity)
    result = await resource_service.compare_document_content_revisions(identity, before_revision,
        after_revision, actor_agent_id=ctx.agent_id, region=region)
    return json.dumps(result, ensure_ascii=False)


@mcp_tool("document", name="document_sharing", approval="enabled",
    approval_reason="Read the current permissions of an accessible document",
    description="Inspect a Document's grants, recipient options and lock_version. Requires ownership or write access and a delegated Document scope. Pass its document:// URI or UUID. Use the returned recipient IDs and lock_version with document_share. Paginate options with offset/limit (50 by default, maximum 500).",
    effect_policy="read", concurrency_policy="safe")
async def document_sharing(ctx: McpToolContext, document_id: str, search: str = "",
    kind: Literal["agent", "user", "team"] | None = None, offset: int = 0, limit: int = 50) -> str:
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError("Invalid recipient pagination")
    state = await item_sharing.agent_sharing(_identity(document_id), agent_id=ctx.agent_id, enforce_tool_scope=True)
    options = [option for option in state.options if (kind is None or option.kind == kind)
        and search.strip().casefold() in option.label.casefold()]
    return json.dumps({**state.model_dump(mode="json", exclude={"options"}),
        "options": [option.model_dump(mode="json") for option in options[offset:offset+limit]],
        "total": len(options), "has_more": offset+limit < len(options)}, ensure_ascii=False)


async def _share_target(
    ctx: McpToolContext, *,
    recipient: Literal["requester"] | None,
    agent_id: int | None, user_id: int | None, team_id: int | None,
) -> tuple[Literal["agent", "user", "team"], int]:
    targets: list[tuple[Literal["agent", "user", "team"], int]] = []
    if agent_id is not None:
        targets.append(("agent", agent_id))
    if user_id is not None:
        targets.append(("user", user_id))
    if team_id is not None:
        targets.append(("team", team_id))
    if recipient == "requester" and not targets:
        from app.task.facade import root_task_requester_user

        requester = (await root_task_requester_user(ctx.task_id, agent_id=ctx.agent_id)
                     if ctx.task_id is not None else None)
        if requester is None:
            raise ToolCallRejectedError(
                'recipient="requester" requires your current root Task with a verified human requester. '
                "For another recipient, use one explicit ID from document_sharing."
            )
        return "user", requester
    if recipient is not None or len(targets) != 1 or targets[0][1] <= 0:
        raise ToolArgumentsRejectedError(
            "Choose exactly one recipient. To share with the human who requested your current root Task, "
            'pass recipient="requester". Otherwise pass one positive user_id, agent_id or team_id '
            "from document_sharing. The document ID and lock version do not identify a recipient."
        )
    return targets[0]


async def _document_share_preflight(ctx: McpToolContext, arguments: dict[str, Any]) -> dict[str, Any]:
    kind, target = await _share_target(ctx, recipient=arguments.get("recipient"),
        agent_id=arguments.get("agent_id"), user_id=arguments.get("user_id"), team_id=arguments.get("team_id"))
    if arguments.get("recipient") is not None:
        return {"recipient_kind": kind, "recipient_id": target}
    # Keep the authorization fingerprint of explicit-ID calls made before the shortcut existed.
    arguments.pop("recipient", None)
    if arguments.get("access") is None:
        arguments["access"] = "edit"
    return {}


@mcp_tool("document", name="document_share", approval="ask",
    approval_reason="Change access to a shared Document",
    authorization_preflight=_document_share_preflight,
    description=(
        'Share a Document you own or can edit within your delegated Document scope. For delivery to the human requester of your current root Task, '
        'pass recipient="requester" and access="read". For other recipients, pass exactly one '
        'agent_id, user_id or team_id returned by document_sharing. Get expected_lock_version '
        'from document_sharing. Access defaults to read for the requester shortcut and edit '
        'for explicit IDs. Access "none" removes only the selected direct grant. Confirm the grant '
        'in the result before transmitting the URI.'
    ))
async def document_share(ctx: McpToolContext, document_id: str, agent_id: int | None = None,
    access: Literal["read", "edit", "none"] | None = None, team_id: int | None = None,
    user_id: int | None = None, expected_lock_version: int | None = None,
    recipient: Annotated[Literal["requester"] | None, Field(
        description="Explicitly select the human requester of your current root Task. Combine with no recipient ID.",
    )] = None) -> str:
    kind, target = await _share_target(ctx, recipient=recipient, agent_id=agent_id,
                                       user_id=user_id, team_id=team_id)
    identity = _identity(document_id)
    state = await item_sharing.update_agent_sharing(identity, agent_id=ctx.agent_id,
        kind=kind, target_id=target, access=access or ("read" if recipient == "requester" else "edit"),
        expected_lock_version=expected_lock_version,
        document_only=True, enforce_tool_scope=True)
    return json.dumps({"document_id": str(identity), "uri": f"document://{identity}",
        **state.model_dump(mode="json", exclude={"options"})}, ensure_ascii=False)
