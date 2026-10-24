"""Protect evidence integrity; real-agent ability is qualified separately."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from tests.agent_team_pilot.cases import CASES, mission
from tests.agent_team_pilot.evidence import assess, delegation_observations, readable_html, redact
from tests.agent_team_pilot.runner import deliveries_settled, finished, page_items
from tests.agent_team_pilot.seed import PILOT_EMAIL, configuration, require_isolated_database


@pytest.mark.parametrize("accepted,secondary_failure", [(False, ""), (True, ""), (True, "observer"), (True, "capture")])
def test_browser_submission_failure_preserves_admitted_work_evidence_without_resubmission(tmp_path, accepted, secondary_failure):
    root = tmp_path / "source"
    for name in ("bin", "back", "front", "e2e"):
        (root / name).mkdir(parents=True)
    script = root / "bin/agent-team-pilot.sh"
    shutil.copyfile(Path(__file__).resolve().parents[2] / "bin/agent-team-pilot.sh", script)
    for name in ("Makefile", "compose.agent-team.yaml"):
        (root / name).write_text("")
    config = root / "provider.json"
    config.write_text('{"base_url":"https://example.invalid/v1","model":"synthetic"}')
    executables = tmp_path / "executables"
    executables.mkdir()
    (executables / "git").write_text('#!/bin/sh\nif [ "$1" = rev-parse ]; then echo synthetic; fi\n')
    docker = executables / "docker"
    docker.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with Path(os.environ["PILOT_COMMANDS"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
directory = Path(os.environ["TEAM_PILOT_ARTIFACTS"])
if "submit" in args:
    if os.environ["PILOT_ACCEPTED"] == "1":
        (directory / "submission.json").write_text('{"message":{"id":"synthetic-receipt"}}')
    sys.exit(41)
if "observer" in args and "--preflight" not in args and "tests.agent_team_pilot.diagnostics" not in args:
    (directory / "collected.json").write_text('{"recorded_inference_cost_usd":0.012}')
    if os.environ["PILOT_SECONDARY_FAILURE"] == "observer":
        sys.exit(9)
if "capture" in args and os.environ["PILOT_SECONDARY_FAILURE"] == "capture":
    sys.exit(8)
if "tests.agent_team_pilot.diagnostics" in args:
    sys.stdin.read()
''')
    for executable in executables.iterdir():
        executable.chmod(0o755)
    commands = tmp_path / "commands.jsonl"
    result = subprocess.run(["bash", str(script), "run", "--config", str(config)],
        env={**os.environ, "PATH": f"{executables}:{os.environ['PATH']}", "PILOT_COMMANDS": str(commands),
             "PILOT_ACCEPTED": "1" if accepted else "0", "PILOT_SECONDARY_FAILURE": secondary_failure},
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 41, result.stderr
    calls = [json.loads(line) for line in commands.read_text().splitlines()]
    assert sum("submit" in call for call in calls) == 1
    observations = [call for call in calls if "observer" in call and "--preflight" not in call
                    and "tests.agent_team_pilot.diagnostics" not in call]
    assert len(observations) == int(accepted)
    assert sum("capture" in call for call in calls) == int(accepted)
    run = next((root / "artifacts/agent-team").glob("run.*"))
    assert (run / "collected.json").exists() == accepted
    assert "down" in calls[-1]


def manifest():
    return {"case": "baseline", "mode": "directed", "leader_id": 1, "peer_ids": [2, 3], "criteria": ["A source-backed result"]}


def test_success_states_cannot_approve_content_or_invent_collaboration():
    result = assess(manifest(), {"termination": "completed", "tasks": [{"id": "root", "agent_id": 1, "status": "SUCCESS"}]})
    assert result["collaboration"] == "no_delegation_observed"
    assert result["content_acceptance"] == "pending_human_review"
    assert result["editorial_observations"]["target_observed"] is False
    assert result["criteria"][0]["verdict"] == "unreviewed"


@pytest.mark.parametrize("html,duplicates", [
    ("<h2>Risques</h2>\n<h2>Risques</h2><p>À vérifier.</p>", ["Risques"]),
    ("<h2>Risques &amp; limites</h2><h2><strong>Risques &amp; limites</strong></h2>", ["Risques & limites"]),
    ("<h2>Risques</h2><p>Premier dossier.</p><h2>Risques</h2>", []),
    ("<h2>Risques</h2><h3>Risques</h3>", []),
])
def test_editorial_observation_detects_adjacent_duplicate_headings_without_approving_content(html, duplicates):
    result = assess({**manifest(), "target_uri": "document://synthetic-target"}, {
        "termination": "completed", "tasks": [],
        "documents": [{"item": {"id": "synthetic-target", "payload": {"text": html}}}],
    })
    assert result["editorial_observations"] == {"target_observed": True, "adjacent_duplicate_headings": duplicates}
    assert result["content_acceptance"] == "pending_human_review"
    assert all(item["verdict"] == "unreviewed" for item in result["criteria"])


def test_delegation_requires_a_real_colleague_task_and_retains_its_identity():
    tasks = [
        {"id": "leader-leaf", "agent_id": 1, "parent_id": "root", "status": "SUCCESS"},
        {"id": "wait", "agent_id": 2, "parent_id": "root", "status": "SUCCESS", "is_coordination": True},
        {"id": "colleague-a", "agent_id": 2, "source_task_id": "root", "status": "SUCCESS"},
        {"id": "colleague-b", "agent_id": 3, "parent_id": "root", "status": "EXEC"},
        {"id": "queued", "agent_id": 2, "parent_id": "root", "status": "DISPATCH"},
        {"id": "unrelated", "agent_id": 3, "status": "SUCCESS"},
    ]
    result = delegation_observations(tasks, 1, {2, 3})
    assert result["contribution_tasks"] == ["galaris://task/colleague-a", "galaris://task/colleague-b", "galaris://task/queued"]
    assert result["completed_contributions"] == 1
    assert result["active_contributor_agents"] == [3]


def test_partial_collection_cannot_conclude_no_delegation():
    assert assess(manifest(), {"termination": "timeout", "tasks": []})["collaboration"] == "not_established"


@pytest.mark.parametrize("case", ["amendment", "amendments", "peer_failure"])
def test_untriggered_situation_is_not_a_qualified_scenario(case):
    config = {**manifest(), "case": case, "fault": {"agent_id": 3}}
    assert assess(config, {"termination": "completed", "tasks": []})["scenario_exercised"] is False
    if case == "peer_failure":
        leader_failed = {"termination": "completed", "tasks": [{"id": "root", "agent_id": 1, "status": "ERROR"}]}
        assert assess(config, leader_failed)["scenario_exercised"] is False
        peer_failed = {"termination": "completed", "tasks": [{"id": "finance", "agent_id": 3, "status": "ERROR"}]}
        assert assess(config, peer_failed)["scenario_exercised"] is True


def test_terminated_round_does_not_hide_active_or_paused_children():
    observed = {"rounds": [{"finished_at": "2040-01-01"}], "tasks": [{"status": "DISPATCH", "paused": True}]}
    assert not finished(observed)
    observed["tasks"][0]["status"] = "SUCCESS"
    assert finished(observed)
    assert not finished({"rounds": [], "tasks": []})
    assert not deliveries_settled([{"notification_state": "PENDING"}])
    assert not deliveries_settled([{"notification_state": "UNKNOWN"}])
    assert deliveries_settled([{"notification_state": "DELIVERED"}, {"notification_state": "SKIPPED"}])


def test_evidence_redacts_nested_credentials_and_free_text_without_erasing_usage():
    result = redact({"access_token": "token-value", "nested": [{"api_key": "key-value", "input_tokens": 123}],
                     "error": "failed with secret-value and Bearer token-value"}, ("secret-value",))
    assert result["nested"][0]["input_tokens"] == 123
    for value in ("token-value", "key-value", "secret-value"):
        assert value not in json.dumps(result)


def test_readable_report_keeps_content_without_activating_document_code():
    assert readable_html("<h1>Quartz</h1><p>48 places &amp; accès.</p><script>secret()</script><style>p{color:red}</style>") == "Quartz\n48 places & accès."


@pytest.mark.parametrize("environment,host,database", [("dev", "db-team", "agent_team_pilot"),
    ("qualification", "postgres", "agent_team_pilot"), ("qualification", "db-team", "galaris")])
def test_seed_refuses_every_non_pilot_database(environment, host, database):
    with pytest.raises(RuntimeError):
        require_isolated_database(environment, host, database)
    require_isolated_database("qualification", "db-team", "agent_team_pilot")


def test_prepare_accepts_placeholder_but_execute_requires_real_configuration(tmp_path):
    path = tmp_path / "provider.json"
    path.write_text(json.dumps({"base_url": "https://example.invalid/v1", "model": "replace-with-your-model"}))
    configuration(path, execute=False)
    with pytest.raises(ValueError):
        configuration(path, execute=True)
    path.write_text(json.dumps({"base_url": "https://secret@example.test/v1", "model": "fixture"}))
    with pytest.raises(ValueError):
        configuration(path, execute=False)
    path.write_text(json.dumps({"base_url": "https://example.test/v1", "model": "fixture", "api_key": "synthetic-secret"}))
    with pytest.raises(ValueError, match="credentials"):
        configuration(path, execute=False)


def test_fixture_identity_can_use_the_real_login_contract():
    from core.user.schemas import UserLogin
    assert str(UserLogin(email=PILOT_EMAIL, password="synthetic-password").email) == PILOT_EMAIL


@pytest.mark.asyncio
@pytest.mark.parametrize("decision,team_authorized", [(None, True), (1, True), (None, False)])
async def test_preflight_checks_profile_and_team_before_accepting_a_paid_mission(tmp_path, monkeypatch, decision, team_authorized):
    import httpx
    from tests.agent_team_pilot import runner
    config = {**manifest(), "room_id": "synthetic-room", "document_ids": [], "profile_id": 2, "model_id": 1, "team_id": 4}
    (tmp_path / "manifest.json").write_text(json.dumps(config))
    (tmp_path / "_session.json").write_text(json.dumps({"email": "synthetic@example.com", "password": "synthetic-secret"}))
    requests = []
    def endpoint(request):
        requests.append((request.method, request.url.path))
        if request.url.path == "/api/auth/login-json":
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        if request.url.path == "/api/llm-profiles/2":
            return httpx.Response(200, json={"decision_llm_id": decision, **{
                tier: 1 for tier in ("text_ultra_low_llm_id", "text_low_llm_id", "text_standard_llm_id", "text_high_llm_id")}})
        if request.url.path == "/api/agents/teams/agents":
            return httpx.Response(200, json=[{"id": agent, "team_ids": [4] if agent != 3 or team_authorized else []} for agent in (1, 2, 3)])
        return httpx.Response(200, json={"items": [], "total": 0})
    original = httpx.AsyncClient
    monkeypatch.setattr(runner.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(endpoint), **kwargs))
    if decision is None and team_authorized:
        assert await runner.observe(tmp_path, "http://backend:8000", preflight=True) == 0
        assert json.loads((tmp_path / "preflight.json").read_text())["profile_validated"]
    else:
        with pytest.raises(RuntimeError, match="Decisions binding" if decision is not None else "Pilot team"):
            await runner.observe(tmp_path, "http://backend:8000", preflight=True)
        assert not (tmp_path / "preflight.json").exists()
    assert all(method == "GET" or path == "/api/auth/login-json" for method, path in requests)


def test_mission_contains_inputs_but_never_the_acceptance_oracle():
    text = mission(["document://source"], "document://target", [{"name": "Peer", "id": 2, "role": "finance"}], "directed")
    assert "document://source" in text and "document://target" in text
    assert all(criterion not in text for case in CASES.values() for criterion in case.criteria)
    assert "7200" not in text and "48" not in text


@pytest.mark.asyncio
@pytest.mark.parametrize("accepted", [True, False])
@pytest.mark.parametrize("followup", [True, False])
async def test_amendment_waits_for_two_executing_peers_and_never_resends_uncertain_delivery(tmp_path, monkeypatch, accepted, followup):
    import httpx
    from tests.agent_team_pilot import runner
    config = {**manifest(), "case": "amendment", "executable": True,
              "room_id": "room", "document_ids": [], "amendment": "Synthetic budget update",
              "limits": {"timeout_seconds": 60}}
    if followup:
        config.update(case="amendments", followup_amendment="Synthetic second budget update")
    (tmp_path / "manifest.json").write_text(json.dumps(config))
    (tmp_path / "_session.json").write_text(json.dumps({"email": "synthetic@example.com", "password": "synthetic-secret"}))
    (tmp_path / "submission.json").write_text(json.dumps({"message": {"id": "initial-message"}}))
    polls = 0
    submissions = []

    def endpoint(request):
        nonlocal polls
        path = request.url.path
        if path == "/api/auth/login-json":
            return httpx.Response(200, json={"access_token": "synthetic-token"})
        if path.endswith("/tasks"):
            polls += 1
            complete = polls >= 4
            return httpx.Response(200, json={"total": 3, "items": [
                {"id": "root", "agent_id": 1, "status": "SUCCESS" if complete else "DISPATCH"},
                {"id": "peer-a", "agent_id": 2, "parent_id": "root", "status": "SUCCESS" if complete else "EXEC"},
                {"id": "peer-b", "agent_id": 3, "parent_id": "root",
                 "status": "SUCCESS" if complete else "DISPATCH" if polls == 1 else "EXEC"},
            ]})
        if request.method == "POST" and path.endswith("/messages"):
            submissions.append({"poll": polls, **json.loads(request.content)})
            return httpx.Response(200, json={"id": "accepted-amendment"}) if accepted else httpx.Response(503)
        if path.endswith("/messages"):
            return httpx.Response(200, json={"total": 1, "items": [
                {"id": "initial-message", "created_at": "2040-01-01", "text": "Synthetic mission"}]})
        if path.endswith("/activity"):
            return httpx.Response(200, json={"total": 1, "items": [
                {"id": "round", "finished_at": "2040-01-01" if polls >= 4 else None}]})
        if path.endswith("/dataset"):
            return httpx.Response(200, json={"task_links": [{"notification_state": "DELIVERED"}],
                "task_amendments": [{"id": "admitted-first"}] if submissions else []})
        if path.endswith(("/documents", "/history")):
            return httpx.Response(200, json={"items": [], "total": 0})
        if path.endswith(("/full", "/budget", "/activity/round")):
            return httpx.Response(200, json={})
        raise AssertionError(f"Unexpected request {request.method} {path}")

    original = httpx.AsyncClient
    monkeypatch.setattr(runner.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(endpoint), **kwargs))
    code = await runner.observe(tmp_path, "http://backend:8000")
    assert len(submissions) == (2 if followup and accepted else 1) and submissions[0]["poll"] == 2
    assert submissions[0]["text"] == config["amendment"]
    evidence = json.loads((tmp_path / "evidence.json").read_text())
    assert evidence["amendment_sent"] is accepted
    assert evidence["amendment_attempt"]["client_message_id"] == submissions[0]["client_message_id"]
    assert code == (0 if accepted else 2)
    if accepted:
        assert evidence["amendment_message"]["id"] == "accepted-amendment"
        assert polls >= 4  # Two executing snapshots must not trigger a second send.
        if followup:
            assert submissions[1]["text"] == config["followup_amendment"]
            assert submissions[1]["poll"] > submissions[0]["poll"]
            assert evidence["followup_amendment_attempt"]["preceding_amendment_ids"] == ["admitted-first"]
    else:
        assert evidence["termination"] == "collection_error"


@pytest.mark.asyncio
async def test_paginated_evidence_is_complete_and_http_failures_are_not_empty_results():
    import httpx
    def endpoint(request):
        page = int(request.url.params["page"])
        return httpx.Response(200, json={"items": [{"id": page}], "total": 2})
    async with httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(endpoint)) as client:
        assert await page_items(client, "/tasks") == [{"id": 1}, {"id": 2}]
    async with httpx.AsyncClient(base_url="https://example.test", transport=httpx.MockTransport(lambda _: httpx.Response(403))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await page_items(client, "/tasks")


@pytest.mark.asyncio
@pytest.mark.parametrize("broken_collection", [False, True])
async def test_observer_retains_actual_results_and_collection_errors(tmp_path, monkeypatch, broken_collection):
    import httpx
    from tests.agent_team_pilot import runner
    config = {**manifest(), "executable": True, "room_id": "room", "document_ids": ["source", "target"],
              "target_uri": "document://target", "limits": {"timeout_seconds": 60}}
    (tmp_path / "manifest.json").write_text(json.dumps(config))
    (tmp_path / "_session.json").write_text(json.dumps({"email": "synthetic@example.com", "password": "synthetic-secret"}))
    (tmp_path / "submission.json").write_text(json.dumps({"channel": "browser", "message": {"id": "sent"}}))
    task = {"id": "root", "agent_id": 1, "status": "SUCCESS"}
    requests = []
    def endpoint(request):
        requests.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/auth/login-json":
            return httpx.Response(200, json={"access_token": "synthetic-bearer"})
        if path.endswith("/tasks"):
            return httpx.Response(503) if broken_collection else httpx.Response(200, json={"items": [task], "total": 1})
        if path.endswith("/activity"):
            return httpx.Response(200, json={"items": [{"id": "round", "finished_at": "2040-01-01"}], "total": 1})
        if path.endswith("/messages"):
            return httpx.Response(200, json={"items": [{"id": "initial-message", "created_at": "2040-01-01", "text": "Synthetic mission"}], "total": 1})
        if path.endswith("/documents"):
            # The real document-list API requires this message anchor. Empty
            # mocked histories previously concealed that runtime contract.
            assert request.url.params["from_message_id"] == "initial-message"
            return httpx.Response(200, json={"items": [], "total": 0})
        if path.endswith("/history"):
            return httpx.Response(200, json={"items": [], "total": 0})
        if path.endswith("/dataset"):
            return httpx.Response(200, json={"task_links": [{"task_id": "root", "notification_state": "DELIVERED"}]})
        if path.startswith("/api/documents/"):
            return httpx.Response(200, json={"item": {"id": path.rsplit("/", 1)[1], "payload": {"text": "<p>Synthetic final content</p>"}}})
        if path.endswith(("/full", "/budget", "/activity/round")):
            return httpx.Response(200, json={"id": "root", "result": "Synthetic final result"})
        raise AssertionError(f"Unexpected endpoint {path}")
    original_client = httpx.AsyncClient
    monkeypatch.setattr(runner.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(endpoint), **kwargs))
    code = await runner.observe(tmp_path, "http://backend:8000")
    result = json.loads((tmp_path / "assessment.json").read_text())
    assert result["content_acceptance"] == "pending_human_review"
    assert not any(method == "POST" and path.endswith("/messages") for method, path in requests)
    assert "synthetic-secret" not in (tmp_path / "evidence.json").read_text()
    if broken_collection:
        assert code == 2 and result["collaboration"] == "not_established"
        assert result["termination"] == "collection_error"
    else:
        assert code == 0 and result["collaboration"] == "no_delegation_observed"
        assert json.loads((tmp_path / "evidence.json").read_text())["documents"]
        assert "Synthetic final content" in (tmp_path / "report.md").read_text()
