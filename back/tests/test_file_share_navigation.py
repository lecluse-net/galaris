"""Protect the evidence behind the MCP/directory decision, using synthetic inputs."""

import copy
import json

import pytest
from fastmcp import Client

from scripts.file_share_navigation.analysis import compare, report, score
from scripts.file_share_navigation.corpus import generate
from scripts.file_share_navigation.service import application


@pytest.mark.parametrize(
    "answer",
    ['{"count":true}', '{"count":1.0}', '{"count":1} then {"count":2}', '{"count":2,"extra":0}'],
)
def test_exact_scoring_rejects_coercion_and_partial_answers(answer):
    assert not score(answer, {"count": 1})
    assert score('{"uri":"fixture://a","values":[1,2]}', {"uri": "fixture://a", "values": [1, 2]})
    assert not score('{"values":[2,1]}', {"values": [1, 2]})
    assert score('Explanation. ```json\n{"count":1,"note":"synthetic"}\n```', {"count": 1})


def test_frozen_corpus_is_synthetic_reproducible_and_has_distinct_holdouts(tmp_path):
    pilot = generate(tmp_path / "pilot", phase="pilot", repetitions=1)
    decision = generate(tmp_path / "decision", phase="decision")
    assert pilot["corpus_sha256"] == decision["corpus_sha256"]
    assert len(decision["cases"]) == 12
    assert len(decision["runs"]) == 120
    assert {c["id"] for c in pilot["cases"]}.isdisjoint(c["id"] for c in decision["cases"])
    with pytest.raises(FileExistsError):
        generate(tmp_path / "decision", phase="decision")


def measurements(manifest):
    return [
        {
            **r,
            "passed": True,
            "access_verified": True,
            "usage_verified": True,
            "cost_usd": 1.0,
            "input_tokens": 20,
            "output_tokens": 10,
        }
        for r in manifest["runs"]
    ]


def test_pairing_cost_of_failures_and_safety_gate(tmp_path):
    manifest = generate(tmp_path / "campaign", phase="decision", repetitions=1)
    rows = measurements(manifest)
    with pytest.raises(ValueError, match="Missing"):
        compare(rows[:-1], manifest)
    with pytest.raises(ValueError, match="duplicate"):
        compare(rows + [rows[0]], manifest)
    for row in rows:
        row["cost_usd"] = 0.5 if row["arm"] == "filesystem" else 1.0
    result = compare(rows, manifest)
    assert result["decision"] == "continue_design"
    assert result["cost_reduction_ci95"] == [0.5, 0.5]
    rows[0]["identity_error"] = True
    assert compare(rows, manifest)["decision"] == "stop_fuse"
    rows[0].pop("identity_error")
    rows[0]["usage_verified"] = False
    assert compare(rows, manifest)["decision"] == "invalid_measurement"
    rows[0]["usage_verified"] = True
    for row in rows:
        row["passed"] = False
    result = compare(rows, manifest)
    assert result["arms"]["mcp"]["cost_usd"] == 12.0
    assert result["cost_reduction"] is None


def test_repetitions_do_not_create_independent_missions(tmp_path):
    manifest = generate(tmp_path / "campaign", phase="decision", repetitions=1)
    rows = measurements(manifest)
    for row in rows:
        row["passed"] = row["arm"] == "filesystem" if row["case"] == "nested" else True
    once = compare(rows, manifest)
    repeated_manifest = copy.deepcopy(manifest)
    repeated_rows = []
    for repetition in range(1, 6):
        repeated_rows.extend({**row, "repetition": repetition} for row in rows)
    repeated_manifest["runs"] = repeated_rows
    repeated = compare(repeated_rows, repeated_manifest)
    assert repeated["success_gain_ci95"] == once["success_gain_ci95"]
    assert repeated["paired_case_count"] == 12


def test_missing_runtime_or_accounting_evidence_cannot_produce_a_decision(tmp_path):
    root = tmp_path / "campaign"
    generate(root, phase="pilot", repetitions=1)
    with pytest.raises(ValueError, match="incomplete"):
        report(root)
    (root / "corpus/cross/order.txt").write_text("changed synthetic content")
    with pytest.raises(ValueError, match="corpus changed"):
        report(root)
    manifest = json.loads((root / "manifest.json").read_text())
    manifest["experiment_source_sha256"] = "invalid-source-hash"
    (root / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="sources changed"):
        report(root)


@pytest.mark.asyncio
async def test_real_mcp_facade_continuations_binary_failures_and_arm_isolation(
    tmp_path, monkeypatch
):
    from app.file_share import mcp as file_tools, resource_service

    # application() patches external seams only; restore them after this test.
    for module, name in (
        (file_tools, "_resource_context"),
        (resource_service, "describe_targets"),
        (resource_service, "resolve_resource_transport_with_service"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    root = tmp_path / "campaign"
    manifest = generate(root, phase="pilot", repetitions=1)
    controls = {run["id"]: run["id"] for run in manifest["runs"]}
    app = application(root, {}, controls)
    # Use the assembled HTTP transport, not a mocked MCP handler.
    import httpx
    from fastmcp.client.transports import StreamableHttpTransport

    transport = httpx.ASGITransport(app=app)
    mcp_run = next(r["id"] for r in manifest["runs"] if r["arm"] == "mcp")
    fs_run = next(r["id"] for r in manifest["runs"] if r["arm"] == "filesystem")

    def factory(**kwargs):
        return httpx.AsyncClient(transport=transport, **kwargs)

    async with app.router.lifespan_context(app):
        async with Client(
            StreamableHttpTransport(
                "http://test/mcp/",
                headers={"Authorization": "Bearer " + mcp_run},
                httpx_client_factory=factory,
            )
        ) as client:
            first = await client.call_tool(
                "file_list", {"uri": "fixture://pagination/", "max_entries": 500}
            )
            page = json.loads(first.content[0].text)
            assert len(page["entries"]) == 500 and page["truncated"]
            second = await client.call_tool(
                "file_list",
                {"uri": "fixture://pagination/", "cursor": page["next_cursor"], "max_entries": 500},
            )
            end = json.loads(second.content[0].text)
            assert len(end["entries"]) == 7 and not end["truncated"]
            first_read = await client.call_tool(
                "file_read", {"uri": "fixture://reading/ledger.txt"}
            )
            read = json.loads(first_read.content[0].text)
            assert "LT-5318" not in read["content"] and read["next_offset"] > 0
            final = await client.call_tool(
                "file_read", {"uri": "fixture://reading/ledger.txt", "offset": read["total"] - 30}
            )
            assert "LT-5318" in json.loads(final.content[0].text)["content"]
            binary = await client.call_tool("file_read", {"uri": "fixture://binary/signature.bin"})
            assert json.loads(binary.content[0].text)["encoding"] == "base64"
            with pytest.raises(Exception, match="fixture"):
                await client.call_tool("file_read", {"uri": "document://"})
            with pytest.raises(Exception, match="enumeration failure"):
                await client.call_tool("file_list", {"uri": "fixture://faults/interrupted/"})
        async with Client(
            StreamableHttpTransport(
                "http://test/mcp/",
                headers={"Authorization": "Bearer " + fs_run},
                httpx_client_factory=factory,
            )
        ) as client:
            with pytest.raises(Exception, match="disabled"):
                await client.call_tool("file_list", {"uri": "fixture://"})
    assert (root / "metrics" / (mcp_run + ".json")).exists()


@pytest.mark.asyncio
async def test_model_relay_retains_accounting_and_rejects_conflicting_parameters(
    tmp_path, monkeypatch
):
    import httpx
    from scripts.file_share_navigation import service

    root = tmp_path / "campaign"
    manifest = generate(root, phase="pilot", repetitions=1)
    run = manifest["runs"][0]["id"]
    real_client = httpx.AsyncClient
    requests = []
    fail = False
    secret = "credential-that-must-stay-private"

    class Upstream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, **kwargs):
            requests.append(kwargs)
            if fail:
                return httpx.Response(503, json={"error": {"message": "x" * 490 + secret}})
            return httpx.Response(
                200,
                json={
                    "id": "synthetic-call",
                    "model": "synthetic-model",
                    "provider": "fixture-provider",
                    "choices": [
                        {"message": {"role": "assistant", "content": "{}"}, "finish_reason": "stop"}
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 2, "cost": 0.01},
                },
            )

    for module, name in (
        (service.file_tools, "_resource_context"),
        (service.resource_service, "describe_targets"),
        (service.resource_service, "resolve_resource_transport_with_service"),
    ):
        monkeypatch.setattr(module, name, getattr(module, name))
    app = application(
        root,
        dict(
            base_url="https://openrouter.ai/api/v1",
            api_key=secret,
            model="synthetic-model",
            upstream="fixture-provider",
        ),
        {run: "synthetic-token"},
    )
    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: Upstream())
    async with real_client(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/v1/synthetic-token/chat/completions",
            json={
                "model": "ignored",
                "messages": [{"role": "user", "content": "synthetic request"}],
                "reasoning_effort": "medium",
            },
        )
        assert response.status_code == 200
        submitted = requests[0]["json"]
        assert submitted["reasoning"] == {"effort": "none"} and "reasoning_effort" not in submitted
        assert submitted["provider"] == {"allow_fallbacks": False, "order": ["fixture-provider"]}
        metrics = json.loads((root / "metrics" / (run + ".json")).read_text())
        assert (
            metrics["usage_verified"]
            and metrics["input_tokens"] == 20
            and metrics["cost_usd"] == 0.01
        )
        fail = True
        response = await client.post("/v1/synthetic-token/chat/completions", json={"messages": []})
        assert response.status_code == 503
        saved = (root / "metrics" / (run + ".json")).read_text()
        metrics = json.loads(saved)
        assert "credential" not in saved and "[redacted]" in saved
        assert (
            not metrics["usage_verified"]
            and metrics["model_calls"] == 2
            and len(metrics["usage"]) == 1
        )
        response = await client.post("/v1/unknown/chat/completions", json={"messages": []})
        assert response.status_code == 403 and len(requests) == 2
