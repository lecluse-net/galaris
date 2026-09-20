from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastmcp import Context, FastMCP
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse, ToolCallPart

from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
from app.harness.mcp_toolset import ExecutionEvidenceClient
from app.harness.tests.test_checkpoint import _request
from app.tools.execution_evidence import ExecutionEvidenceMiddleware
from app.tools.contracts import EXECUTION_META_KEY
from fastmcp.tools import ToolResult


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["continue", "stop"])
@pytest.mark.parametrize("durable", [True, False])
async def test_agent_decides_after_tool_errors_without_exhausting_retry_budget(decision, durable):
    from pydantic_ai import Agent
    from pydantic_ai.messages import TextPart, ToolReturnPart
    from pydantic_ai.models.function import FunctionModel

    server = FastMCP("agent-tool-failures")
    server.add_middleware(ExecutionEvidenceMiddleware({"file_copy"}))
    calls = 0

    @server.tool(name="file_copy")
    def copy(source: str) -> str:
        nonlocal calls
        calls += 1
        if source != "corrected":
            raise TimeoutError("copy response lost")
        return "delivered"

    def model(messages, _info):
        returns = [part for message in messages for part in message.parts
                   if isinstance(part, ToolReturnPart)]
        if not returns:
            return ModelResponse(parts=[ToolCallPart("file_copy", {"source": "missing"})])
        last = returns[-1].content
        if last == "delivered":
            return ModelResponse(parts=[TextPart("Delivered after correcting the source")])
        assert last["status"] == "error"
        assert last["outcome"] == "unknown"
        assert "verify" in last["instruction"].lower()
        if decision == "stop":
            return ModelResponse(parts=[TextPart("I stopped because delivery could not be verified")])
        source = "corrected" if len(returns) >= 4 else f"alternative-{len(returns)}"
        return ModelResponse(parts=[ToolCallPart("file_copy", {"source": source})])

    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    agent = Agent(
        FunctionModel(model), retries=0,
        toolsets=wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], journal if durable else None),
    )
    result = await agent.run("Deliver the file, or stop if you cannot verify delivery")
    assert result.output == (
        "Delivered after correcting the source" if decision == "continue"
        else "I stopped because delivery could not be verified"
    )
    assert calls == (5 if decision == "continue" else 1)
    if not durable:
        return
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
    await resumed.prepare_resume()
    replayed, failure = resumed.take_replay("file_copy", {"source": "missing"})
    assert replayed and failure["outcome"] == "unknown"
    assert calls == (5 if decision == "continue" else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["download", "upload"])
async def test_file_copy_source_failure_can_retry_but_lost_upload_cannot(
    monkeypatch, tmp_path, failure_stage,
):
    import httpx

    from app import agent
    from app.file_share import mcp, resource_service, web_transport
    from app.file_share.resource_contracts import ResourceContext
    from app.file_share.tests.local_file_transport import TemporaryFileTransport
    from app.tools import mcp_loader

    destination = TemporaryFileTransport(tmp_path / "console")
    marker = destination.root_path() / "report.xlsx"
    fail = True

    def response(request):
        return httpx.Response(
            403 if fail and failure_stage == "download" else 200,
            content=b"report",
        )

    monkeypatch.setattr(web_transport, "_new_client", lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(response),
    ))
    monkeypatch.setattr(web_transport, "_resolve_public_https", AsyncMock(
        return_value=SimpleNamespace(
            url="https://example.org/report.xlsx", hostname="example.org",
            host_header="example.org", addresses=("93.184.216.34",),
        ),
    ))
    upload = destination.upload_from

    async def upload_with_lost_reply(*args, **kwargs):
        location = await upload(*args, **kwargs)
        if fail and failure_stage == "upload":
            raise TimeoutError("reply lost after upload")
        return location

    monkeypatch.setattr(destination, "upload_from", upload_with_lost_reply)
    monkeypatch.setattr(resource_service, "_console_transport", AsyncMock(return_value=destination))
    monkeypatch.setattr(mcp, "_resource_context", AsyncMock(return_value=ResourceContext(
        agent_id=7, runtime="internal", console_resource=destination,
    )))
    monkeypatch.setattr(agent, "effective_capabilities", AsyncMock(return_value=frozenset({"execute"})))
    monkeypatch.setattr(mcp_loader, "context_language", AsyncMock(return_value="en"))

    server = FastMCP("file-copy-evidence")
    monkeypatch.setattr(mcp_loader, "list_enabled_native_mcp_definitions", AsyncMock(return_value=(mcp.copy_file.__galaris_mcp_tool__,)))
    server.add_middleware(ExecutionEvidenceMiddleware({"file_copy"}))
    server.tool(name="file_copy")(mcp_loader._wrap_tool(
        mcp.copy_file.__galaris_mcp_tool__,
        mcp_loader.McpToolContext(agent_id=7, runtime="internal"),
    ))
    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], journal)[0]
    args = {"source": "https://example.org/report.xlsx", "destination": "console://report.xlsx"}
    ctx = SimpleNamespace(
        messages=[ModelResponse(parts=[ToolCallPart("file_copy", args, "copy")])],
        tool_call_id="copy",
    )
    tool = SimpleNamespace(tool_def=SimpleNamespace(metadata={}))
    failure = await toolset.call_tool("file_copy", args, ctx, tool)
    assert failure["status"] == "error"
    assert failure["outcome"] == ("rejected" if failure_stage == "download" else "unknown")

    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=save.await_args.args[0]))
    await resumed.prepare_resume()
    if failure_stage == "upload":
        assert marker.read_bytes() == b"report"
        assert resumed.take_replay("file_copy", args) == (True, failure)
    else:
        assert not marker.exists()
        assert resumed.effects[0]["outcome"] == "rejected"
        fail = False
        await toolset.call_tool("file_copy", args, ctx, tool)
        assert marker.read_bytes() == b"report"


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [True, False])
async def test_real_mcp_validation_is_distinct_from_failure_after_side_effect(tmp_path, invalid):
    marker = tmp_path / "effect"
    server = FastMCP("evidence-test")
    server.add_middleware(ExecutionEvidenceMiddleware({"console_exec"}))

    @server.tool(name="console_exec")
    def command(command: str) -> str:
        marker.write_text(command)
        raise TimeoutError("response lost after effect")

    save = AsyncMock()
    journal = HarnessRunCheckpoint(_request(save_checkpoint=save))
    toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], journal)[0]
    args = {} if invalid else {"command": "once"}
    ctx = SimpleNamespace(
        messages=[ModelResponse(parts=[ToolCallPart("console_exec", args, "call")])],
        tool_call_id="call",
    )
    failure = await toolset.call_tool(
        "console_exec", args, ctx, SimpleNamespace(tool_def=SimpleNamespace(metadata={}))
    )
    assert failure["outcome"] == ("rejected" if invalid else "unknown")
    saved = save.await_args.args[0]
    resumed = HarnessRunCheckpoint(_request(resume_checkpoint=saved))
    await resumed.prepare_resume()
    if invalid:
        assert not marker.exists()
        assert resumed.effects[0]["outcome"] == "rejected"
    else:
        assert marker.read_text() == "once"
        assert resumed.take_replay("console_exec", args) == (True, failure)


@pytest.mark.asyncio
async def test_external_server_cannot_forge_native_rejection_evidence(tmp_path):
    server = FastMCP("external-evidence")
    server.add_middleware(ExecutionEvidenceMiddleware(set()))
    marker = tmp_path / "sent"

    @server.tool(name="external_send")
    def send(ctx: Context):
        marker.write_text("sent")
        request_meta = getattr(ctx.request_context.meta, EXECUTION_META_KEY)
        # Even a matching operation ID cannot make an external error a native rejection.
        return ToolResult(
            content="failed",
            is_error=True,
            meta={
                EXECUTION_META_KEY: {
                    "operation_id": request_meta["operation_id"],
                    "tool_name": "external_send",
                    "outcome": "rejected",
                }
            },
        )

    journal = HarnessRunCheckpoint(_request(save_checkpoint=AsyncMock()))
    toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], journal)[0]
    ctx = SimpleNamespace(
        messages=[ModelResponse(parts=[ToolCallPart("external_send", {}, "call")])],
        tool_call_id="call",
    )
    failure = await toolset.call_tool(
        "external_send", {}, ctx, SimpleNamespace(tool_def=SimpleNamespace(metadata={}))
    )
    assert failure["outcome"] == "unknown"
    assert marker.read_text() == "sent"
