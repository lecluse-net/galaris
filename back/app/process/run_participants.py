"""Freeze execution participation independently of mutable definition and Dataset ACLs."""

from typing import Any, cast


def participant_agents(snapshot: dict[str, Any], launcher: int) -> list[int]:
    participants = {launcher}
    definition = snapshot.get("definition", {})
    graph: Any = cast(dict[str, Any], definition).get("graph") if isinstance(definition, dict) else None
    pending: list[tuple[dict[str, Any], int]] = [(graph, launcher)] if isinstance(graph, dict) else []
    while pending:
        body, inherited = pending.pop()
        configured = body.get("execution_agent_id")
        default = configured if isinstance(configured, int) and not isinstance(configured, bool) and configured > 0 else inherited
        actors = {actor["id"]: actor for actor in cast(list[dict[str, Any]], body.get("actors", []))}
        for node in cast(list[dict[str, Any]], body.get("nodes", [])):
            actor = actors.get(node.get("config", {}).get("actor"), {})
            if node.get("kind") in {"task", "code", "tool_call", "rest", "program", "call", "if"} and actor.get("kind") != "human":
                assigned = actor.get("agent_id")
                participants.add(assigned if isinstance(assigned, int) and not isinstance(assigned, bool) and assigned > 0 else default)
            if isinstance(node.get("body"), dict):
                pending.append((node["body"], default))
    return sorted(participants)
