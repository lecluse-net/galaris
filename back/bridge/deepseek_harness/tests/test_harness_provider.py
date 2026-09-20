from types import SimpleNamespace
from unittest.mock import AsyncMock, call
from uuid import uuid4

import pytest

from app.harnesses.contracts import HarnessProvisioningRequest
from bridge.deepseek_harness import harness_provider


def _request() -> HarnessProvisioningRequest:
    return HarnessProvisioningRequest(
        harness_id=uuid4(),
        catalogue_harness_id=uuid4(),
        agent_id=7,
        agent_code="alice_dev",
        name="DeepSeek",
        base_url=None,
        model=None,
        revision=1,
    )


def test_runtime_name_is_stable_across_harness_assignments() -> None:
    first = harness_provider._runtime_name("Alice_DEV", "one")
    second = harness_provider._runtime_name("Alice-DEV", "two")

    assert first == "Alice_DEV-agent"
    assert second == "Alice-DEV-agent"
    assert harness_provider._runtime_name("Alice_DEV", "two") == first


def test_runtime_targets_the_current_deepseek_harness_preview() -> None:
    assert harness_provider._DSH_VERSION == "0.1.6-alpha.1"
    assert harness_provider._DSH_REF == "0a15e36e7f82b6ed45af6fa9759f29b40dcd965d"


def test_environment_serializer_rejects_multiline_secrets() -> None:
    with pytest.raises(ValueError, match="HARNESS_API_TOKEN"):
        harness_provider._serialize_env({"HARNESS_API_TOKEN": "secret\nleak"})


def test_runtime_image_uses_filesystem_node_carrier_for_native_pty() -> None:
    dockerfile = (harness_provider._DEFAULT_AGENT_DIR / "Dockerfile").read_text(
        encoding="utf-8"
    )

    assert "COPY --from=dsh-builder /usr/local/bin/node /usr/local/bin/node" in dockerfile
    assert "DSH_RUNTIME_MODE=node" in dockerfile


def test_runtime_todo_tool_declares_sequential_execution_policy() -> None:
    cordis = (harness_provider._DEFAULT_AGENT_DIR / "cordis.yml").read_text(
        encoding="utf-8"
    )

    import yaml
    patches = yaml.load(cordis, Loader=yaml.BaseLoader)
    todo = next(item for item in patches if item.get("id") == "tool-todo")
    assert todo["config"]["allowParallelInProgress"] == "false"


@pytest.mark.asyncio
async def test_provider_provisions_before_starting_and_returns_generated_coordinates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = SimpleNamespace(id=7, code="alice_dev")
    request = _request()
    manager = harness_provider.harness_manager
    create = AsyncMock()
    list_instances = AsyncMock(return_value=[])
    start = AsyncMock(return_value="started")
    synchronize = AsyncMock(
        return_value=("http://galaris-dsh-alice:8080/v1", "executor-model", "skills-v1")
    )
    monkeypatch.setattr(type(manager), "configured", property(lambda _self: True))
    monkeypatch.setattr(manager, "create_instance", create)
    monkeypatch.setattr(manager, "list_instances", list_instances)
    monkeypatch.setattr(manager, "run_action", start)
    monkeypatch.setattr(harness_provider, "_synchronize", synchronize)

    class FakeClient:
        def __init__(self, *, base_url, token):
            assert base_url == "http://galaris-dsh-alice:8080/v1"
            assert token == "api-token"

        async def list_models(self):
            return ["executor-model"]

    monkeypatch.setattr(harness_provider, "OpenAIHarnessClient", FakeClient)

    result = await harness_provider.provider.provision(
        agent,
        request,
        token="api-token",
    )

    create.assert_awaited_once_with("alice_dev")
    synchronize.assert_awaited_once_with(agent, request, api_token="api-token")
    start.assert_awaited_once_with("alice_dev", "start")
    assert result.base_url == "http://galaris-dsh-alice:8080/v1"
    assert result.model == "executor-model"
    assert result.token == "api-token"
    assert result.metadata["model_gateway"] == "galaris"
    assert result.metadata["deepseek_harness_version"] == "0.1.6-alpha.1"
    assert result.metadata["deepseek_harness_ref"] == harness_provider._DSH_REF
    assert result.metadata["galaris_extensions"] is True
    assert result.metadata["model_passthrough"] is True
    assert {"execute", "mcp", "memory", "skills"} <= result.capabilities


@pytest.mark.asyncio
async def test_skill_projection_replaces_the_isolated_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source = tmp_path / "SKILL.md"
    source.write_text("---\nname: demo\ndescription: Demo\n---\n", encoding="utf-8")
    snapshot = SimpleNamespace(
        skill_codes=("demo",),
        files=(
            SimpleNamespace(
                skill_code="demo",
                relative_path="SKILL.md",
                source=source,
            ),
        ),
        revision="abcdef1234567890",
    )
    delete_tree = AsyncMock(return_value=True)
    upload = AsyncMock(return_value=source.stat().st_size)
    monkeypatch.setattr(
        harness_provider,
        "build_skill_projection",
        AsyncMock(return_value=snapshot),
    )
    monkeypatch.setattr(harness_provider.harness_manager, "delete_tree", delete_tree)
    monkeypatch.setattr(harness_provider.harness_manager, "upload_file_from", upload)

    revision = await harness_provider._sync_skills(SimpleNamespace(id=7, code="alice"))

    assert revision == snapshot.revision
    assert delete_tree.await_args_list == [call("alice", "data/skills")]
    upload.assert_awaited_once_with(
        "alice",
        "data/skills/demo/SKILL.md",
        source,
    )
