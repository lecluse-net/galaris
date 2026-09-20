"""File sharing and transfer MCP tools exposed to Galaris agents."""

from __future__ import annotations

import base64
import binascii
from typing import Literal

from app.tools import RecoverableToolError
from app.tools.mcp_loader import McpToolContext, context_language, mcp_tool

from .resource_contracts import ResourceContext
from .resource_service import (
    _json_model,
    list_schemes,
    preferred_local_resource_uri,
    resource_append,
    resource_copy,
    resource_create,
    resource_delete,
    resource_edit,
    resource_info,
    resource_list,
    resource_move,
    resource_read,
    resource_search,
    resource_write,
)


async def _context_language(ctx: McpToolContext) -> str:
    return await context_language(ctx)


async def _resource_context(ctx: McpToolContext) -> ResourceContext:
    from app.skill import can_manage_skill_resources

    return ResourceContext(
        agent_id=ctx.agent_id,
        runtime=ctx.runtime,
        task_id=ctx.task_id,
        console_resource=ctx.resource("console"),
        language=await _context_language(ctx),
        skill_management=await can_manage_skill_resources(ctx.agent_id),
    )


def _decode_content(
    content: str,
    encoding: Literal["utf-8", "base64"],
) -> bytes:
    if encoding == "utf-8":
        return content.encode("utf-8")
    try:
        return base64.b64decode(content, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("content must be valid base64 when encoding='base64'.") from exc


@mcp_tool(
    "file_sharing",
    name="file_schemes",
    description=(
        "List the resource URI schemes accessible to this agent, with examples and exact "
        "file capabilities. Use it before choosing a store. console:// is advertised only "
        "when a console is active; otherwise no local filesystem exists."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def file_schemes(ctx: McpToolContext) -> str:
    """Return native and connected virtual-file providers."""

    return _json_model({"schemes": await list_schemes(await _resource_context(ctx))})


@mcp_tool(
    "file_sharing",
    name="file_list",
    description=(
        "List a resource collection by URI, for example console://reports/, "
        "document://<uuid>/attachments/, nextcloud://Shared/, telegram://<room-id>/, or "
        "galaris://task/. With Gestion des compétences access, galaris://skill/ lists managed "
        "skill packages and galaris://skill/<code>/ lists their files. "
        "When uri is omitted, console:// is listed if the run owns a console; otherwise "
        "an explicit provider URI is required. "
        "Connected provider schemes are always exact Tool codes."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def list_files(
    ctx: McpToolContext,
    uri: str = "",
    recursive: bool = False,
    max_entries: int = 100,
    cursor: str = "",
) -> str:
    """List files through the URI facade."""

    resource_ctx = await _resource_context(ctx)
    selected_uri = uri or preferred_local_resource_uri(resource_ctx, "")
    result = await resource_list(
        resource_ctx,
        selected_uri,
        recursive=recursive,
        max_entries=max_entries,
        cursor=cursor or None,
    )
    return _json_model(result)


@mcp_tool(
    "file_sharing",
    name="file_info",
    description="Show normalized metadata and capabilities for one resource URI.",
    effect_policy="read",
    concurrency_policy="safe",
)
async def file_info(
    ctx: McpToolContext,
    uri: str,
    include_checksum: bool = False,
) -> str:
    """Show provider-independent resource metadata."""

    return _json_model(
        await resource_info(
            await _resource_context(ctx),
            uri,
            include_checksum=include_checksum,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_search",
    description=(
        "Search below a collection URI by name or bounded UTF-8 content. Returns canonical "
        "resource URIs that can be passed directly to every compatible file tool. Use "
        "galaris:// to find tasks, conversation rounds, goals, goal cycles, and assigned "
        "processes; authorized skill files are searched below galaris://skill/. "
        "galaris:// supports name and text search, not semantic search; use memory:// for "
        "semantic recall."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def search_files(
    ctx: McpToolContext,
    uri: str,
    query: str,
    mode: Literal["name", "text", "semantic"] = "name",
    recursive: bool = True,
    max_results: int | None = None,
    cursor: str = "",
) -> str:
    """Search one virtual resource tree."""

    if mode == "semantic" and uri.strip().lower().startswith("galaris://"):
        raise RecoverableToolError(
            "galaris:// supports only name and text search. Retry with mode='text', "
            "or use memory:// for semantic recall."
        )

    result = await resource_search(
        await _resource_context(ctx),
        uri,
        query,
        mode=mode,
        recursive=recursive,
        max_results=max_results,
        cursor=cursor or None,
    )
    return _json_model(result)


@mcp_tool(
    "file_sharing",
    name="file_read",
    description=(
        "Read any resource URI. UTF-8 text is returned in bounded pages; small binary files "
        "are returned completely as base64. Keep large binaries out of model context: pass their "
        "URI to a specialized tool, or copy to console:// only when console software must handle "
        "them. Use next_offset to continue text reads. HTML Memory/document pages contain complete numbered blocks, format, profile and revision. Their offsets count blocks, not characters. A large indivisible block reports its required max_chars (up to 2 MB); the default budget stays 20,000."
    ),
    effect_policy="read",
    concurrency_policy="safe",
)
async def read_file(
    ctx: McpToolContext,
    uri: str,
    offset: int = 0,
    max_chars: int = 20_000,
) -> str:
    """Read automatically detected text or binary content."""

    return _json_model(
        await resource_read(
            await _resource_context(ctx), uri, offset=offset, max_chars=max_chars
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_create",
    description=(
        "Create a new complete text or binary file and return its canonical URI. Pass an exact "
        "file path, or a collection path plus name. Use path='document://' to let Galaris assign "
        "a new document URI. document_type is immutable: 'html' (default) or 'dataset'. "
        "For a dataset, pass valid JSON with encoding='utf-8'. For an HTML document, content must be an editorial HTML fragment "
        "with encoding='utf-8', for example '<h1>Report</h1><p>Findings.</p>', not Markdown "
        "or a full HTML page with html/head/body tags. Documents accept ordinary form, style and script elements, "
        "rendered in an isolated sandbox alongside editable prose. No special app manifest is required. "
        "A form declares a Dataset with data-dataset='document://UUID', optionally data-dataset-alias='entries'. "
        "Inside the sandbox use galaris.datasets.read/append/replace, with the read revision for mutations; "
        "share both the page and Dataset explicitly. Source editing preserves this ordinary HTML. "
        "Use document://<uuid>/attachments/ plus name to attach a file to "
        "an editable document. Choose a destination scheme returned by file_schemes; console:// "
        "is the local filesystem whenever it is advertised. With Gestion des compétences access, "
        "create package files below "
        "galaris://skill/<code>/. Creating a new skill starts with its valid SKILL.md. "
        "Existing resources are never overwritten."
    ),
)
async def create_file(
    ctx: McpToolContext,
    path: str,
    content: str = "",
    encoding: Literal["utf-8", "base64"] = "utf-8",
    name: str = "",
    document_type: Literal["html", "dataset"] | None = None,
) -> str:
    """Create a complete resource without overwriting an existing one."""

    return _json_model(
        await resource_create(
            await _resource_context(ctx),
            path,
            _decode_content(content, encoding),
            name=name,
            document_type=document_type,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_write",
    description=(
        "Replace one existing complete file. Pass text with encoding='utf-8' or binary bytes "
        "as base64. document:// and galaris://skill/ files accept expected_revision from "
        "file_read (mandatory for documents); Dataset replacements must remain valid JSON. "
        "Document types cannot change. Use file_create for new resources. Skill definitions are validated and "
        "system skills remain read-only."
    ),
)
async def write_file(
    ctx: McpToolContext,
    uri: str,
    content: str,
    encoding: Literal["utf-8", "base64"] = "utf-8",
    expected_revision: int | None = None,
) -> str:
    """Write a complete text or binary file through a provider adapter."""

    return _json_model(
        await resource_write(
            await _resource_context(ctx),
            uri,
            _decode_content(content, encoding),
            expected_revision=expected_revision,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_append",
    description=(
        "Append UTF-8 text to a resource URI when its provider supports append. HTML documents require complete valid blocks and expected_revision. "
        "Dataset appends must leave the complete document valid JSON; normally use file_write or file_edit instead. Use it to "
        "extend local files, document:// resources, and authorized galaris://skill/ files "
        "without resending existing content."
    ),
)
async def append_file(ctx: McpToolContext, uri: str, content: str, expected_revision: int | None = None) -> str:
    """Append text through a provider adapter."""

    return _json_model(
        await resource_append(await _resource_context(ctx), uri, content, expected_revision=expected_revision)
    )


@mcp_tool(
    "file_sharing",
    name="file_edit",
    description=(
        "Replace a 1-based inclusive range in an existing UTF-8 resource. For HTML documents, "
        "start_line/end_line identify complete blocks returned by file_read, content is valid HTML, "
        "and expected_revision is mandatory. Dataset documents use actual lines and require "
        "expected_revision; the complete result must remain valid JSON. For "
        "example start_line=10 and end_line=14 rewrites lines 10 through 14. Binary resources "
        "are rejected. Pass expected_revision for document:// or galaris://skill/ when one is "
        "already known."
    ),
)
async def edit_file(
    ctx: McpToolContext,
    uri: str,
    start_line: int,
    end_line: int,
    content: str,
    expected_revision: int | None = None,
) -> str:
    """Edit one explicit inclusive line range."""

    return _json_model(
        await resource_edit(
            await _resource_context(ctx),
            uri,
            start_line=start_line,
            end_line=end_line,
            content=content,
            expected_revision=expected_revision,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_copy",
    description=(
        "Copy bytes between any two resource URIs with bounded memory. An existing collection "
        "or provider space keeps the source name even when its trailing / is omitted; use / "
        "to identify a collection that does not exist yet. Use console://... to copy "
        "files into or out of the local console filesystem. For document://, use the empty "
        "collection to create a document (application/json sources become Dataset documents), an existing UUID with overwrite=true, or "
        "document://<uuid>/attachments/ to add the source as an attachment."
    ),
)
async def copy_file(
    ctx: McpToolContext,
    source: str,
    destination: str,
    overwrite: bool = False,
) -> str:
    """Copy a file across virtual providers."""

    return _json_model(
        await resource_copy(
            await _resource_context(ctx),
            source,
            destination,
            overwrite=overwrite,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_move",
    description=(
        "Move or rename a local file, mutable connected-provider file, or an "
        "auxiliary file within the same authorized galaris://skill/<code>/ directory. A "
        "collection or provider-space destination keeps the source name, including when an "
        "existing collection is given without its trailing /. Cross-provider moves require "
        "deletion "
        "support; memory://, document://, Galaris business snapshots, SKILL.md, and Web sources "
        "must use file_copy instead."
    ),
)
async def move_file(
    ctx: McpToolContext,
    source: str,
    destination: str,
    overwrite: bool = False,
) -> str:
    """Move a resource without silently losing a copied source."""

    return _json_model(
        await resource_move(
            await _resource_context(ctx),
            source,
            destination,
            overwrite=overwrite,
        )
    )


@mcp_tool(
    "file_sharing",
    name="file_delete",
    description=(
        "Delete one resource URI when its provider supports generic deletion. Memory, documents "
        "themselves, Messenger attachments, Galaris business snapshots, and SKILL.md require "
        "their domain tool. A document attachment can be deleted when the agent may edit its "
        "parent document. Authorized auxiliary galaris://skill/ files can also be deleted."
    ),
)
async def delete_file(ctx: McpToolContext, uri: str) -> str:
    """Delete through an authorized provider adapter."""

    return _json_model(await resource_delete(await _resource_context(ctx), uri))
