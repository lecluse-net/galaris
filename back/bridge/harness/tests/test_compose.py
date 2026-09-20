from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
import yaml

from bridge.harness import configured_compose, merge_compose_defaults
from core.params import Params, params_service


@pytest.mark.parametrize("service_name", ["agent", "codex", "harness"])
def test_shared_compose_targets_every_provider_without_duplicate_networks(service_name):
    template = {"services": {service_name: {"image": "runtime", "read_only": True}}}
    original = deepcopy(template)
    defaults = """services:
  agent:
    networks: [agents-net]
    cpus: 2
networks:
  agents-net:
    external: true
    name: agents-net
"""
    result = merge_compose_defaults(template, defaults, service_name=service_name)
    assert template == original
    assert list(result["services"]) == [service_name]
    assert result["services"][service_name] == {
        "image": "runtime", "read_only": True, "networks": ["agents-net"], "cpus": 2,
    }
    assert result["networks"] == {"agents-net": {"external": True, "name": "agents-net"}}
    assert merge_compose_defaults(result, defaults, service_name=service_name) == result


@pytest.mark.parametrize("defaults", [None, "", " "])
def test_empty_shared_defaults_do_not_add_any_network(defaults):
    template = {"services": {"agent": {"image": "runtime"}}}
    assert merge_compose_defaults(template, defaults, service_name="agent") == template


@pytest.mark.parametrize("defaults", ["[]", "null", "hello"])
def test_invalid_shared_defaults_fail_explicitly(defaults):
    with pytest.raises(ValueError, match="mapping"):
        merge_compose_defaults({}, defaults, service_name="agent")


@pytest.mark.asyncio
async def test_render_reads_the_common_parameter(monkeypatch):
    getter = AsyncMock(return_value="services:\n  agent:\n    networks: [remote]\n")
    monkeypatch.setattr(params_service, "get", getter)
    rendered = await configured_compose("services:\n  codex:\n    image: runtime\n", service_name="codex")
    getter.assert_awaited_once_with(Params.HARNESS_DEFAULT_COMPOSE)
    assert yaml.safe_load(rendered)["services"]["codex"]["networks"] == ["remote"]
