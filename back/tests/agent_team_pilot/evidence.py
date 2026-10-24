"""Conservative observations: runtime success never substitutes for human acceptance."""

import hashlib
import json
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

TERMINAL = {"SUCCESS", "ERROR"}
SECRET_KEY = re.compile(r"(^|_)(password|secret|api_key|access_token|refresh_token|mcp_token|runtime_token|authorization|cookie|credentials|lease_token|token_encrypted|token_hash)($|_)", re.I)


def redact(value: Any, secrets: tuple[str, ...] = ()) -> Any:
    if isinstance(value, dict):
        return {key: "[redacted]" if SECRET_KEY.search(str(key)) else redact(item, secrets) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[redacted]")
        value = re.sub(r"Bearer\s+[^\s\"<>]+", "Bearer [redacted]", value, flags=re.I)
        return value
    return value


def write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def delegation_observations(tasks: list[dict[str, Any]], leader: int, peers: set[int]) -> dict[str, Any]:
    # A planned leaf assigned to the leader is not a colleague contribution.
    delegated = [task for task in tasks if task.get("agent_id") in peers and
                 (task.get("parent_id") or task.get("source_task_id")) and
                 not task.get("is_coordination", False)]
    return {
        "leader": leader,
        "contributor_agents": sorted({task["agent_id"] for task in delegated}),
        "contribution_tasks": [f"galaris://task/{task['id']}" for task in delegated],
        "completed_contributions": sum(task.get("status") == "SUCCESS" for task in delegated),
        "active_contributor_agents": sorted({task["agent_id"] for task in delegated
            if task.get("status") == "EXEC" and not task.get("paused")}),
    }


def assess(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    tasks = evidence.get("tasks", [])
    observed = delegation_observations(tasks, manifest["leader_id"], set(manifest["peer_ids"]))
    complete = evidence.get("termination") == "completed"
    if not complete:
        collaboration = "not_established"
    elif not observed["contributor_agents"]:
        collaboration = "no_delegation_observed"
    elif len(observed["contributor_agents"]) < 2:
        collaboration = "one_colleague_observed"
    else:
        collaboration = "two_colleagues_observed"
    recovery = recovery_observations(manifest, evidence)
    return {
        "schema_version": "galaris.agent-team-pilot/v1",
        "case": manifest["case"], "mode": manifest["mode"],
        "termination": evidence.get("termination", "unknown"),
        "collaboration": collaboration,
        "observations": observed,
        "amendment_sent": bool(evidence.get("amendment_sent")),
        "followup_amendment_sent": bool(evidence.get("followup_amendment_sent")),
        "scenario_exercised": (manifest["case"] not in {"amendment", "amendments"} or bool(evidence.get("amendment_sent")))
            and (not manifest.get("followup_amendment") or bool(evidence.get("followup_amendment_sent")))
            and (manifest["case"] != "peer_failure" or any(task.get("agent_id") == (manifest.get("fault") or {}).get("agent_id")
                 and task.get("status") == "ERROR" for task in tasks))
            and (not manifest.get("restart_after_amendment") or recovery["restart_exercised"]),
        **recovery,
        "physical_model_call_count": len(evidence.get("physical_model_calls", [])),
        "recorded_inference_cost_usd": sum(call.get("inference_cost", 0) for call in evidence.get("physical_model_calls", [])),
        "cost_is_estimated": any(call.get("cost_estimated", True) for call in evidence.get("physical_model_calls", [])),
        "task_errors": [f"galaris://task/{task['id']}" for task in tasks if task.get("status") == "ERROR"],
        "content_acceptance": "pending_human_review",
        "editorial_observations": editorial_observations(manifest, evidence),
        "criteria": [{"criterion": item, "verdict": "unreviewed", "evidence": ""} for item in manifest["criteria"]],
        "evidence_sha256": digest(evidence),
        "limitations": ["A SUCCESS state proves neither complete content nor successful coordination.",
                        "Task costs may include descendants; they are not summed as an invoice.",
                        "No semantic judge was called; human acceptance remains required."],
    }


def recovery_observations(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    restart = evidence.get("restart", {})
    before, after = restart.get("backend-before", {}), restart.get("backend-after", {})
    killed = restart.get("backend-killed", {})
    database_before, database_after = restart.get("database-before", {}), restart.get("database-after", {})
    fault = killed.get("exit_code") == 137 and killed.get("status") == "exited"
    database_preserved = bool(database_before) and database_before == database_after
    process_changed = bool(before.get("pid")) and before.get("pid") != after.get("pid") and (
        before.get("container") == after.get("container") and before.get("started_at") != after.get("started_at"))
    boots = evidence.get("boots", [])
    bootstrap_preserved = len(boots) == 2 and boots[0].get("seeded") is True and boots[1].get("seeded") is False
    baseline = evidence.get("before-restart", {})
    completed = {item["id"]: item for item in baseline.get("tasks", [])
                 if item.get("agent_id") in manifest.get("peer_ids", []) and item.get("status") == "SUCCESS"}
    final_tasks = {item["id"]: item for item in evidence.get("tasks", [])}
    pending = evidence.get("restart_request", {}).get("pending_amendments", [])
    fault_point_verified = bool(completed and pending) and all(item.get("id") and item.get("applied_at") is None for item in pending)
    restored = {item["id"] for inspection in evidence.get("after-restart", {}).get("round_inspections", [])
                for item in inspection.get("task_amendments", [])}
    instruction_retained = bool(pending) and all(item["id"] in restored for item in pending)
    pending_across_fault = instruction_retained
    for inspection in evidence.get("after-restart", {}).get("round_inspections", []):
        for item in inspection.get("task_amendments", []):
            if item["id"] not in {amendment["id"] for amendment in pending} or item.get("applied_at") is None:
                continue
            try:
                applied = datetime.fromisoformat(item["applied_at"].replace("Z", "+00:00"))
                started = datetime.fromisoformat(after["started_at"].replace("Z", "+00:00"))
                pending_across_fault = pending_across_fault and applied >= started
            except (KeyError, ValueError, TypeError):
                pending_across_fault = False
    retained = []
    for identifier, task in completed.items():
        final = final_tasks.get(identifier, {})
        old_calls = {item["id"] for item in baseline.get("physical_model_calls", []) if item.get("task_id") == identifier}
        new_calls = {item["id"] for item in evidence.get("physical_model_calls", []) if item.get("task_id") == identifier}
        if final.get("status") == "SUCCESS" and final.get("feedback") == task.get("feedback") and old_calls == new_calls:
            retained.append(identifier)
    notification_ids = sorted({item["notification_message_id"] for item in evidence.get("delivery_links", [])
                               if item.get("notification_state") == "DELIVERED" and item.get("notification_message_id")})
    duplicate_hashes = {}
    for document, revisions in evidence.get("document_revisions", {}).items():
        hashes = [item["content_hash"] for item in revisions]
        duplicates = sorted({value for value in hashes if hashes.count(value) > 1})
        if duplicates:
            duplicate_hashes[document] = duplicates
    target = manifest.get("target_uri", "").removeprefix("document://")
    target_written = any(str(item.get("item", {}).get("id")) == target and item["item"].get("revision", 0) > 1
                         for item in baseline.get("documents", []))
    before_revision = next((item["item"]["revision"] for item in baseline.get("documents", [])
                            if str(item.get("item", {}).get("id")) == target), None)
    committed_rows = [row for row in baseline.get("document_revisions", {}).get(target, [])
                      if row.get("revision") == before_revision and before_revision and before_revision > 1]
    after_rows = evidence.get("after-restart", {}).get("document_revisions", {}).get(target, [])
    committed_retained = bool(committed_rows) and all(any(
        row.get("revision") == old.get("revision") and row.get("content_hash") == old.get("content_hash")
        for row in after_rows) for old in committed_rows)
    delivered_after_restart = bool(notification_ids)
    for identifier in notification_ids:
        message = next((item for item in evidence.get("messages", []) if item.get("id") == identifier), {})
        try:
            delivered_after_restart = delivered_after_restart and datetime.fromisoformat(
                message["created_at"].replace("Z", "+00:00")) >= datetime.fromisoformat(after["started_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError, TypeError):
            delivered_after_restart = False
    phase_verified = (target_written and committed_retained and delivered_after_restart
                      if manifest.get("restart_phase") == "committed_write" else fault_point_verified and pending_across_fault)
    return {"restart_exercised": bool(fault and database_preserved and process_changed and bootstrap_preserved and phase_verified),
            "recovery_observations": {"sigkill_observed": fault, "database_preserved": database_preserved,
                "backend_process_changed": process_changed, "bootstrap_preserved": bootstrap_preserved,
                "pending_instruction_observed_before_fault": fault_point_verified,
                "instruction_retained_after_restart": instruction_retained,
                "instruction_was_pending_across_fault": pending_across_fault,
                "target_written_before_fault": target_written,
                "committed_target_revision_retained": committed_retained,
                "final_delivery_after_restart": delivered_after_restart,
                "completed_peer_tasks_before_restart": sorted(completed), "completed_peer_tasks_retained_without_new_model_calls": retained,
                "final_notification_message_ids": notification_ids, "duplicate_document_content_hashes": duplicate_hashes}}


class _AdjacentHeadings(HTMLParser):
    """Observe a narrow structural defect without rewriting or accepting prose."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading: str | None = None
        self.parts: list[str] = []
        self.previous: tuple[str, str] | None = None
        self.duplicates: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self.heading = tag
            self.parts = []
        elif self.heading is None:
            self.previous = None

    def handle_data(self, data: str) -> None:
        if self.heading:
            self.parts.append(data)
        elif data.strip():
            self.previous = None

    def handle_endtag(self, tag: str) -> None:
        if tag == self.heading:
            text = " ".join("".join(self.parts).split())
            current = (tag, text.casefold())
            if text and self.previous == current:
                self.duplicates.append(text)
            self.previous = current
            self.heading = None


def editorial_observations(manifest: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    target = str(manifest.get("target_uri", "")).removeprefix("document://")
    for document in evidence.get("documents", []):
        item = document.get("item", {})
        if target and str(item.get("id")) == target:
            text = (item.get("payload") or {}).get("text")
            if isinstance(text, str):
                parser = _AdjacentHeadings()
                parser.feed(text)
                parser.close()
                return {"target_observed": True, "adjacent_duplicate_headings": parser.duplicates}
    return {"target_observed": False, "adjacent_duplicate_headings": []}


class _ReadableHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1
        if tag in {"p", "h1", "h2", "h3", "li", "tr", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def readable_html(value: str) -> str:
    parser = _ReadableHTML()
    parser.feed(value)
    return "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())


def render_report(result: dict[str, Any], evidence: dict[str, Any] | None = None, manifest: dict[str, Any] | None = None) -> str:
    observations = result["observations"]
    lines = ["# Qualification du travail d'équipe", "", f"Scénario : {result['case']} ; organisation : {result['mode']}.",
        f"Fin d'exécution : **{result['termination']}**.", f"Collaboration : **{result['collaboration']}**.",
        f"Contributions terminées : {observations['completed_contributions']}.",
        f"Appels physiques enregistrés : {result['physical_model_call_count']} ; coût d'inférence enregistré : {result['recorded_inference_cost_usd']:.6f} USD (estimation : {result['cost_is_estimated']}).",
        f"Consigne modifiée envoyée : {result['amendment_sent']}.",
        f"Situation spécifique exercée : {result['scenario_exercised']}.",
        "", "**Le contenu reste à relire par un humain. Aucun verdict global de réussite n'est attribué.**", "",
        "## Grille de lecture", ""]
    lines.extend(f"- [ ] {item['criterion']}" for item in result["criteria"])
    if manifest and manifest.get("restart_after_amendment"):
        lines.extend(["", "## Reprise après interruption", "",
            f"Redémarrage brutal exercé et stockage conservé : **{result['restart_exercised']}**.",
            "Observations techniques : " + json.dumps(result["recovery_observations"], ensure_ascii=False), ""])
    editorial = result.get("editorial_observations", {})
    if editorial.get("target_observed"):
        duplicates = editorial["adjacent_duplicate_headings"]
        lines.extend(["", f"Titres identiques consécutifs observés : **{len(duplicates)}**."])
        lines.extend(f"- {title}" for title in duplicates)
    if evidence is not None:
        lines.extend(["", "## Contributions observées", ""])
        for task in evidence.get("tasks", []):
            lines.append(f"- galaris://task/{task['id']} — agent {task.get('agent_id')} — {task.get('status')} — {task.get('label', '')}")
        target = manifest.get("target_uri", "").removeprefix("document://") if manifest else ""
        for document in evidence.get("documents", []):
            item = document.get("item", {})
            if str(item.get("id")) == target:
                text = readable_html(item.get("payload", {}).get("text") or "")[:40000]
                lines.extend(["", f"## Document final observé — révision {item.get('revision', '?')}", "",
                              "Texte extrait pour lecture ; la version HTML complète reste dans evidence.json.", ""])
                # Quote inert text; never activate model-produced HTML/scripts in the report.
                lines.extend("> " + line for line in text.splitlines())
        lines.extend(["", "## Messages de la conversation", ""])
        for message in sorted(evidence.get("messages", []), key=lambda item: item.get("created_at", "")):
            sender = message.get("sender") or {}
            name = sender.get("display_name") or message.get("direction", "auteur inconnu")
            lines.append(f"**{name} — {message.get('created_at', '')}**")
            lines.extend("> " + line for line in str(message.get("text", ""))[:10000].splitlines())
            lines.append("")
    lines.extend(["", "## Preuves", "", "Consulter evidence.json (messages, activités, Tasks complètes et révisions documentaires),",
                  "timeline.jsonl (changements observés), et les captures navigateur si disponibles.",
                  f"Empreinte des preuves : `{result['evidence_sha256']}`.", "", "## Limites", ""])
    lines.extend(f"- {item}" for item in result["limitations"])
    return "\n".join(lines) + "\n"
