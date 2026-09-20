"""A lost real SSH response must survive DB reload without another shell effect."""

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import asyncssh
import pytest
from fastmcp import FastMCP
from pydantic import SecretStr
from pydantic_ai.mcp import MCPToolset
from pydantic_ai.messages import ModelResponse, ToolCallPart

from app.agent.contracts import AgentRunCheckpoint
from app.console.ssh_client import SshConnectionConfig, SshExecutionTransport
from app.harness.checkpoint import HarnessRunCheckpoint, wrap_toolsets
from app.harness.mcp_toolset import ExecutionEvidenceClient
from app.harness.tests.test_checkpoint import _request
from app.task.agent_adapter import SqlAlchemyAgentTaskAdapter
from app.task.models import Task, TaskAttempt, TaskStatus
from app.tools.contracts import current_tool_execution
from app.tools.execution_evidence import ExecutionEvidenceMiddleware


@pytest.mark.asyncio
async def test_lost_ssh_ack_recovers_from_database_and_never_repeats_command(db):
    class Authentication(asyncssh.SSHServer):
        def begin_auth(self, username):
            return False

    dropped = False

    async def serve(process):
        nonlocal dropped
        child = await asyncio.create_subprocess_shell(
            process.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        out, err = await child.communicate()
        if " start --cwd " in process.command and not dropped:
            dropped = True
            process.channel.abort()  # The helper dispatched the command; its response is lost.
            return
        process.stdout.write(out)
        process.stderr.write(err)
        process.exit(child.returncode)

    host_key = asyncssh.generate_private_key("ssh-ed25519")
    client_key = asyncssh.generate_private_key("ssh-ed25519")
    listener = await asyncssh.create_server(
        Authentication,
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        process_factory=serve,
        sftp_factory=asyncssh.SFTPServer,
        encoding=None,
    )
    config = SshConnectionConfig(
        connection_id=1,
        host="127.0.0.1",
        port=listener.get_port(),
        username="test",
        private_key=SecretStr(client_key.export_private_key().decode()),
        known_host_key=host_key.export_public_key().decode(),
    )
    helper_directory = tempfile.TemporaryDirectory(prefix="ssh-helper-", dir=Path.home())
    deployed_helper = Path(helper_directory.name) / "galaris-exec"
    deployed_helper.write_bytes(
        (Path(__file__).parents[2] / "console" / "assets" / "galaris-exec").read_bytes()
    )
    deployed_helper.chmod(0o700)

    def transport():
        value = SshExecutionTransport(config)
        value._helper_checked = True
        value._helper_path = str(deployed_helper)
        value._helper_version = "2"
        return value

    first_transport, resumed_transport = transport(), transport()
    token = uuid4()
    task = Task(
        id=uuid4(),
        label="Lost SSH acknowledgement",
        objective="<p>Execute once</p>",
        status=TaskStatus.EXEC,
        lease_token=token,
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        data={},
    )
    attempt = TaskAttempt(
        task_id=task.id,
        attempt_number=1,
        phase="DISPATCH",
        status="CLAIMED",
        worker_id="before-disconnect",
        lease_token=token,
        data={},
    )
    db.add_all([task, attempt])
    await db.commit()
    adapter = SqlAlchemyAgentTaskAdapter()

    async def persist(checkpoint):
        await adapter.persist_agent_run_state(
            task.id,
            expected_objective=task.objective,
            expected_attempt_id=attempt.id,
            data_patch={
                "_agent_run_checkpoint": {
                    "driver_code": checkpoint.driver_code,
                    "runtime_run_id": checkpoint.runtime_run_id,
                    "status": checkpoint.status,
                    "data": checkpoint.data,
                }
            },
        )

    journal = HarnessRunCheckpoint(
        _request(save_checkpoint=AsyncMock(side_effect=persist)), recovery_scope="test-server"
    )
    server = FastMCP("real-ssh")
    server.add_middleware(ExecutionEvidenceMiddleware({"console_exec"}))

    @server.tool(name="console_exec")
    async def execute(command: str, cwd: str):
        context = current_tool_execution()
        context.entered = True
        result = await first_transport.exec_operation(
            command, cwd=cwd, operation_id=context.operation_id, task_id=task.id
        )
        return result.model_dump(mode="json")

    operation_id = None
    try:
        with tempfile.TemporaryDirectory(prefix="ssh-recovery-", dir=Path.home()) as work:
            arguments = {"command": "printf x >> effect; printf receipt", "cwd": work}
            toolset = wrap_toolsets([MCPToolset(ExecutionEvidenceClient(server))], journal)[0]
            ctx = SimpleNamespace(
                messages=[
                    ModelResponse(parts=[ToolCallPart("console_exec", arguments, "call-ssh")])
                ],
                tool_call_id="call-ssh",
            )
            failure = await asyncio.wait_for(
                toolset.call_tool(
                    "console_exec",
                    arguments,
                    ctx,
                    SimpleNamespace(tool_def=SimpleNamespace(metadata={})),
                ),
                15,
            )
            assert failure["outcome"] == "unknown"
            await db.refresh(task)
            saved = AgentRunCheckpoint(**task.data["_agent_run_checkpoint"])
            operation_id = UUID(saved.data["effects"][0]["operation_id"])
            assert saved.data["resume_safe"] is True
            assert saved.data["resume_reconcilable"] is True
            deadline = asyncio.get_running_loop().time() + 10
            while asyncio.get_running_loop().time() < deadline:
                receipt = await resumed_transport.recover_operation(operation_id)
                if receipt and receipt.status != "running":
                    break
                await asyncio.sleep(0.02)
            assert receipt.status == "completed"

            async def recover(effect):
                result = await resumed_transport.recover_operation(UUID(effect["operation_id"]))
                return result is not None, result.model_dump(mode="json") if result else None

            resumed = HarnessRunCheckpoint(
                _request(resume_checkpoint=saved, save_checkpoint=AsyncMock(side_effect=persist)),
                recovery_scope="test-server",
                recover_effect=recover,
            )
            await resumed.prepare_resume()
            replayed, output = resumed.take_replay("console_exec", arguments)
            assert replayed and output["stdout"] == "receipt"
            assert Path(work, "effect").read_text() == "x"
            await db.refresh(attempt)
            assert attempt.data["agent_checkpoint"]["data"]["effects"][0]["status"] == "completed"
            assert len(resumed.restored_messages()[-1].parts) == 1
    finally:
        await first_transport.close()
        await resumed_transport.close()
        listener.close()
        await listener.wait_closed()
        helper_directory.cleanup()
        if operation_id is not None:
            shutil.rmtree(
                Path.home() / ".galaris" / "sessions" / str(operation_id), ignore_errors=True
            )
