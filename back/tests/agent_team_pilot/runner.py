"""Observe the normal authenticated application; never fabricate colleague replies."""

import argparse
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from .evidence import TERMINAL, assess, delegation_observations, digest, redact, render_report, write_json


async def page_items(client: httpx.AsyncClient, path: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items = []
    for page in range(1, 21):
        response = await client.get(path, params={**(params or {}), "page": page, "page_size": 500})
        response.raise_for_status()
        body = response.json()
        items.extend(body["items"])
        if len(items) >= body["total"]:
            return items
    raise RuntimeError("Evidence pagination exceeded 10000 entries; collection is incomplete")


async def snapshot(client: httpx.AsyncClient, manifest: dict[str, Any], *, full: bool) -> dict[str, Any]:
    room = manifest["room_id"]
    tasks = await page_items(client, f"/api/chat/rooms/{room}/tasks")
    rounds = await page_items(client, f"/api/chat/rooms/{room}/activity")
    messages = await page_items(client, f"/api/chat/rooms/{room}/messages")
    result: dict[str, Any] = {"tasks": tasks, "rounds": rounds, "messages": messages}
    if full:
        result["physical_model_calls"] = await page_items(client, "/api/llm-calls/history")
        result["task_details"] = []
        result["round_details"] = []
        result["round_inspections"] = []
        result["budgets"] = []
        for task in tasks:
            response = await client.get(f"/api/tasks/{task['id']}/full")
            response.raise_for_status()
            result["task_details"].append(response.json())
            if task.get("parent_id") is None:
                response = await client.get(f"/api/tasks/{task['id']}/budget")
                response.raise_for_status()
                result["budgets"].append(response.json())
        for round_ in rounds:
            response = await client.get(f"/api/chat/rooms/{room}/activity/{round_['id']}")
            response.raise_for_status()
            result["round_details"].append(response.json())
            response = await client.get(f"/api/conversations/rounds/{round_['id']}/dataset")
            response.raise_for_status()
            result["round_inspections"].append(response.json())
        result["documents"] = []
        anchor = min(messages, key=lambda item: item["created_at"])["id"] if messages else None
        discovered = await page_items(client, f"/api/chat/rooms/{room}/documents", {"from_message_id": anchor}) if anchor else []
        result["working_documents"] = discovered
        for document in sorted(set(manifest["document_ids"]) | {item["id"] for item in discovered}):
            response = await client.get(f"/api/documents/{document}")
            response.raise_for_status()
            result["documents"].append(response.json())
        if manifest.get("restart_after_amendment"):
            result["document_revisions"] = {}
            for document in manifest["document_ids"]:
                response = await client.get(f"/api/documents/{document}/content-revisions", params={"limit": 500})
                response.raise_for_status()
                history = response.json()
                if history["has_more"]:
                    raise RuntimeError("Pilot document history exceeds 500 revisions; evidence is incomplete")
                result["document_revisions"][document] = history["items"]
    return result


async def round_inspections(client: httpx.AsyncClient, rounds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for round_ in rounds:
        response = await client.get(f"/api/conversations/rounds/{round_['id']}/dataset")
        response.raise_for_status()
        result.append(response.json())
    return result


def pending_amendments(inspections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for inspection in inspections for item in inspection.get("task_amendments", [])
            if item.get("applied_at") is None]


async def await_restart(directory: Path, timeout: float = 200) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        path = directory / "restart-receipt.json"
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt.get("status") != "ready":
                raise RuntimeError("Backend restart failed; inspect restart-receipt.json and restart-start.log")
            for name in ("backend-before", "backend-killed", "backend-after", "database-before", "database-after"):
                receipt[name] = json.loads((directory / f"{name}.json").read_text())
            return receipt
        await asyncio.sleep(1)
    raise RuntimeError("Host did not complete the requested backend restart within the timeout")


async def login(client: httpx.AsyncClient, session: dict[str, Any]) -> str:
    response = await client.post("/api/auth/login-json", json=session)
    response.raise_for_status()
    token = response.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token


def finished(observation: dict[str, Any]) -> bool:
    rounds, tasks = observation["rounds"], observation["tasks"]
    return bool(rounds) and all(round_.get("finished_at") for round_ in rounds) and all(
        task.get("status") in TERMINAL for task in tasks)


def deliveries_settled(links: list[dict[str, Any]]) -> bool:
    return all(link.get("notification_state") in {"DELIVERED", "SKIPPED"} for link in links)


async def observe(directory: Path, base_url: str, *, preflight: bool = False) -> int:
    if base_url != "http://backend:8000":
        raise ValueError("Runner only connects to the backend of its isolated Compose project")
    manifest = json.loads((directory / "manifest.json").read_text())
    session = json.loads((directory / "_session.json").read_text())
    secrets = (session["password"],)
    key_path = Path("/run/pilot/api-key")
    if key_path.is_file():
        secrets += (key_path.read_text().strip(),)
    evidence: dict[str, Any] = {"termination": "not_started", "amendment_sent": False}
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        token = await login(client, session)
        secrets += (token,)
        if preflight:
            response = await client.get(f"/api/llm-profiles/{manifest['profile_id']}")
            response.raise_for_status()
            profile = response.json()
            tiers = ("text_ultra_low_llm_id", "text_low_llm_id", "text_standard_llm_id", "text_high_llm_id")
            if profile.get("decision_llm_id") is not None or any(profile.get(tier) != manifest["model_id"] for tier in tiers):
                raise RuntimeError("Pilot requires the configured Chat model in each text tier, without a specialized Decisions binding")
            response = await client.get("/api/agents/teams/agents")
            response.raise_for_status()
            members = {agent["id"] for agent in response.json() if manifest["team_id"] in agent["team_ids"]}
            if members != {manifest["leader_id"], *manifest["peer_ids"]}:
                raise RuntimeError("Pilot team must authorize exactly the three synthetic agents before submission")
            observed = await snapshot(client, manifest, full=True)
            if observed["tasks"] or observed["rounds"] or observed["physical_model_calls"]:
                raise RuntimeError("Preparation unexpectedly created agent work or a model call")
            write_json(directory / "preflight.json", redact({"status": "prepared", "model_calls_requested": False,
                        "document_count": len(observed["documents"]), "physical_model_calls": 0, "leader_id": manifest["leader_id"],
                        "peer_ids": manifest["peer_ids"], "profile_validated": True, "team_validated": True}, secrets))
            return 0
        if not manifest["executable"]:
            raise RuntimeError("Prepared-only stacks cannot submit a model request")
        submission = json.loads((directory / "submission.json").read_text())
        evidence["submission"] = submission
        started = time.monotonic()
        previous = ""
        try:
            while time.monotonic() - started < manifest["limits"]["timeout_seconds"]:
                observed = await snapshot(client, manifest, full=False)
                evidence.update(observed)
                fingerprint = digest(observed)
                if fingerprint != previous:
                    event = {"observed_at": datetime.now(timezone.utc).isoformat(), **observed}
                    with (directory / "timeline.jsonl").open("a", encoding="utf-8") as timeline:
                        timeline.write(json.dumps(redact(event, secrets), ensure_ascii=False) + "\n")
                    previous = fingerprint
                    write_json(directory / "evidence.json", redact(evidence, secrets))
                delegation = delegation_observations(observed["tasks"], manifest["leader_id"], set(manifest["peer_ids"]))
                if manifest.get("amendment") and not evidence["amendment_sent"] and len(delegation["active_contributor_agents"]) >= 2:
                    # The trigger is persisted work, not an arbitrary delay or a forged peer output.
                    message_id = str(uuid4())
                    evidence["amendment_attempt"] = {"client_message_id": message_id,
                        "trigger_tasks": delegation["contribution_tasks"],
                        "trigger_observed_at": datetime.now(timezone.utc).isoformat()}
                    write_json(directory / "evidence.json", redact(evidence, secrets))
                    response = await client.post(f"/api/chat/rooms/{manifest['room_id']}/messages", json={
                        "client_message_id": message_id, "text": manifest["amendment"], "language": "fr",
                    })
                    response.raise_for_status()
                    evidence["amendment_sent"] = True
                    evidence["amendment_message"] = response.json()
                    # Observe the new round before considering the mission finished.
                    continue
                if manifest.get("followup_amendment") and evidence["amendment_sent"] and not evidence.get("followup_amendment_sent"):
                    inspections = await round_inspections(client, observed["rounds"])
                    admitted = [item for inspection in inspections for item in inspection.get("task_amendments", [])]
                    if admitted and any(task.get("status") not in TERMINAL for task in observed["tasks"]):
                        message_id = str(uuid4())
                        evidence["followup_amendment_attempt"] = {"client_message_id": message_id,
                            "preceding_amendment_ids": [item["id"] for item in admitted],
                            "trigger_observed_at": datetime.now(timezone.utc).isoformat()}
                        write_json(directory / "evidence.json", redact(evidence, secrets))
                        response = await client.post(f"/api/chat/rooms/{manifest['room_id']}/messages", json={
                            "client_message_id": message_id, "text": manifest["followup_amendment"], "language": "fr"})
                        response.raise_for_status()
                        evidence["followup_amendment_sent"] = True
                        evidence["followup_amendment_message"] = response.json()
                        continue
                if manifest.get("restart_after_amendment") and evidence["amendment_sent"] and not evidence.get("restart_requested"):
                    completed_peers = [task for task in observed["tasks"] if task.get("agent_id") in manifest["peer_ids"]
                                       and task.get("status") == "SUCCESS"]
                    inspections = await round_inspections(client, observed["rounds"])
                    write_phase = manifest.get("restart_phase") == "committed_write"
                    if completed_peers and (write_phase or pending_amendments(inspections)):
                        response = await client.get("/api/llm-calls", params={
                            "task_ids": [task["id"] for task in completed_peers], "limit": 500})
                        response.raise_for_status()
                        calls = response.json()
                        if len(calls) >= 500:
                            raise RuntimeError("Completed-peer call evidence reaches its collection limit")
                        target_documents = []
                        if manifest.get("target_uri"):
                            target = manifest["target_uri"].removeprefix("document://")
                            response = await client.get(f"/api/documents/{target}")
                            response.raise_for_status()
                            target_documents.append(response.json())
                        # Keep the fault path short: detailed document collection waits
                        # until after restart. Recheck pending state last, then signal.
                        latest = await round_inspections(client, observed["rounds"])
                        pending = pending_amendments(latest)
                        history = []
                        if write_phase and target_documents and target_documents[0]["item"]["revision"] > 1:
                            response = await client.get(f"/api/documents/{target}/content-revisions", params={"limit": 500})
                            response.raise_for_status()
                            body = response.json()
                            if body["has_more"]:
                                raise RuntimeError("Pre-fault history exceeds its collection limit")
                            history = body["items"]
                        links = [link for inspection in latest for link in inspection.get("task_links", [])]
                        committed = bool(history) and not any(link.get("notification_state") == "DELIVERED" for link in links)
                        if committed if write_phase else pending:
                            before = {**observed, "physical_model_calls": calls, "round_inspections": latest,
                                      "documents": target_documents,
                                      "document_revisions": {target: history} if write_phase else {}}
                            write_json(directory / "before-restart.json", redact(before, secrets))
                            request = {"run_id": manifest["run_id"], "requested_at": datetime.now(timezone.utc).isoformat(),
                                       "phase": manifest.get("restart_phase", "pending_amendment"),
                                       "pending_amendments": pending, "completed_peer_tasks": [task["id"] for task in completed_peers],
                                       "evidence_sha256": digest(redact(before, secrets))}
                            evidence["restart_requested"] = True
                            evidence["restart_request"] = request
                            write_json(directory / "evidence.json", redact(evidence, secrets))
                            write_json(directory / "restart-request.json", redact(request, secrets))
                            evidence["restart"] = await await_restart(directory)
                            # Discard pooled connections and authenticate normally against the new process.
                            await client.aclose()
                            client = httpx.AsyncClient(base_url=base_url, timeout=30)
                            secrets += (await login(client, session),)
                            after = await snapshot(client, manifest, full=True)
                            write_json(directory / "after-restart.json", redact(after, secrets))
                            continue
                if finished(observed):
                    # Task terminality can precede the final Chat notification.
                    # Wait for the application's durable delivery decision.
                    links = []
                    for round_ in observed["rounds"]:
                        response = await client.get(f"/api/conversations/rounds/{round_['id']}/dataset")
                        response.raise_for_status()
                        links.extend(response.json().get("task_links", []))
                    evidence["delivery_links"] = links
                    if deliveries_settled(links):
                        evidence["termination"] = "completed"
                        break
                fast_poll = evidence["amendment_sent"] and (
                    (manifest.get("restart_after_amendment") and not evidence.get("restart_requested")) or
                    (manifest.get("followup_amendment") and not evidence.get("followup_amendment_sent")))
                await asyncio.sleep(0.2 if fast_poll else 2)
            else:
                evidence["termination"] = "timeout"
        except Exception as error:
            evidence["termination"] = "collection_error"
            evidence["error"] = redact(f"{type(error).__name__}: {error}", secrets)
        finally:
            evidence["elapsed_seconds"] = round(time.monotonic() - started, 3)
            try:
                evidence.update(await snapshot(client, manifest, full=True))
            except Exception as error:
                evidence["final_collection_error"] = redact(f"{type(error).__name__}: {error}", secrets)
                evidence["termination"] = "collection_error"
            if manifest.get("restart_after_amendment"):
                for name in ("before-restart", "after-restart"):
                    path = directory / f"{name}.json"
                    if path.exists():
                        evidence[name] = json.loads(path.read_text())
                boots = directory / "boots.jsonl"
                evidence["boots"] = [json.loads(line) for line in boots.read_text().splitlines()] if boots.exists() else []
            evidence = redact(evidence, secrets)
            write_json(directory / "evidence.json", evidence)
            result = assess(manifest, evidence)
            write_json(directory / "assessment.json", result)
            (directory / "report.md").write_text(render_report(result, evidence, manifest), encoding="utf-8")
            await client.aclose()
    return 0 if evidence["termination"] == "completed" and (
        not manifest.get("restart_after_amendment") or result.get("restart_exercised")) else 2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", action="store_true")
    parser.add_argument("--reassess", action="store_true")
    args = parser.parse_args()
    directory = Path("/artifacts")
    if args.reassess:
        manifest = json.loads((directory / "manifest.json").read_text())
        evidence = json.loads((directory / "evidence.json").read_text())
        result = assess(manifest, evidence)
        result["retrospective_assessment"] = True
        write_json(directory / "assessment.json", result)
        (directory / "report.md").write_text(render_report(result, evidence, manifest), encoding="utf-8")
        return
    try:
        code = asyncio.run(observe(directory, "http://backend:8000", preflight=args.preflight))
    except Exception as error:
        # Authentication, missing submission or setup errors can precede the
        # observation loop. They must still leave reviewable failure evidence.
        manifest = json.loads((directory / "manifest.json").read_text())
        session_path = directory / "_session.json"
        secrets = (json.loads(session_path.read_text())["password"],) if session_path.exists() else ()
        key_path = Path("/run/pilot/api-key")
        if key_path.is_file():
            secrets += (key_path.read_text().strip(),)
        evidence_path = directory / "evidence.json"
        evidence = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
        evidence.update({"termination": "collection_error", "error": redact(f"{type(error).__name__}: {error}", secrets)})
        write_json(evidence_path, evidence)
        result = assess(manifest, evidence)
        write_json(directory / "assessment.json", result)
        (directory / "report.md").write_text(render_report(result, evidence, manifest), encoding="utf-8")
        print(f"Pilot collection failed ({type(error).__name__}); inspect report.md and services.log.")
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
