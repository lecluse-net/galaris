"""Check oracle consistency without consulting a memory engine or a database."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .catalogue import profiles
from .generate import Corpus, FAMILIES, LANGUAGES, Memory, Query


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value)
    if result.tzinfo is None:
        raise ValueError("Timestamps must have a timezone")
    return result


def prohibited(memory: Memory, query: Query) -> str | None:
    if memory.world_id != query.world_id:
        return "world"
    if memory.state == "forgotten":
        return "forgotten"
    if memory.state != "active" or query.actor_id not in memory.allowed_actor_ids:
        return "access"
    if memory.contact_scope not in (None, query.contact_id):
        return "access"
    if instant(memory.known_at) > instant(query.timestamp):
        return "future_knowledge"
    return None


def validate(corpus: Corpus) -> dict[str, object]:
    memories = {m.id: m for m in corpus.memories}
    memory_ids = set(memories)
    queries = {q.id: q for q in corpus.queries}
    answers = {a.query_id: a for a in corpus.answers}
    if not queries or len(memories) != len(corpus.memories) or len(queries) != len(corpus.queries):
        raise ValueError("Empty queries or duplicate IDs")
    if len(answers) != len(corpus.answers) or set(answers) != set(queries):
        raise ValueError("Exactly one answer per query is required")
    catalogue = {p.key: p for p in profiles()}
    worlds: dict[str, list[Memory]] = {}
    for m in corpus.memories:
        worlds.setdefault(m.world_id, []).append(m)
        if m.language not in LANGUAGES or m.state not in ("active", "revoked", "forgotten"):
            raise ValueError(f"Invalid memory language/state: {m.id}")
        if not m.title or escape(m.source["text"]) not in m.content_html:
            raise ValueError(f"Missing source fact in HTML: {m.id}")
        if instant(m.known_at) > instant(m.recorded_at) or m.source["timestamp"] != m.known_at:
            raise ValueError(f"Inconsistent knowledge/ingestion dates: {m.id}")
        for start, end in ((m.event_start, m.event_end), (m.valid_from, m.valid_until)):
            if start is not None and end is not None and instant(start) >= instant(end):
                raise ValueError(f"Invalid memory interval: {m.id}")
    partitions: dict[str, set[str]] = {}
    coverage: Counter[tuple[str, str, str]] = Counter()
    temporal_cases = 0
    restriction_cache: dict[tuple[str, str, str, str], set[str]] = {}
    for q in corpus.queries:
        a = answers[q.id]
        if q.family not in FAMILIES or q.language not in LANGUAGES or not q.message:
            raise ValueError(f"Invalid scenario: {q.id}")
        if q.profile not in catalogue or catalogue[q.profile].domain != q.domain:
            raise ValueError(f"Invalid domain/profile: {q.id}")
        if q.world_id not in worlds or q.split not in ("development", "validation", "heldout"):
            raise ValueError(f"Invalid world/partition: {q.id}")
        partitions.setdefault(q.profile, set()).add(q.split)
        coverage[(q.world_id, q.family, q.language)] += 1
        instant(q.timestamp).astimezone(ZoneInfo(q.timezone))
        if any(instant(h["timestamp"]) >= instant(q.timestamp) for h in q.history):
            raise ValueError(f"History must precede query: {q.id}")
        if a.response_mode not in ("answer", "clarify", "unknown", "unavailable"):
            raise ValueError(f"Invalid response mode: {q.id}")
        if bool(a.required) != (a.response_mode in ("answer", "clarify")):
            raise ValueError(f"Missing or excessive oracle facets: {q.id}")
        required_ids = {i for g in a.required for i in g.any_of}
        if len({g.facet for g in a.required}) != len(a.required):
            raise ValueError(f"Duplicate facets: {q.id}")
        for g in a.required:
            if not g.any_of or len(set(g.any_of)) != len(g.any_of) or not g.assertion:
                raise ValueError(f"Empty/duplicate oracle alternatives: {q.id}")
        if sum(len(g.any_of) for g in a.required) != len(required_ids):
            raise ValueError(f"Overlapping required facets: {q.id}")
        references = required_ids | set(a.optional_ids) | set(a.forbidden)
        if references - memory_ids:
            raise ValueError(f"Unknown oracle reference: {q.id}")
        if required_ids & set(a.optional_ids) or (required_ids | set(a.optional_ids)) & set(a.forbidden):
            raise ValueError(f"Conflicting oracle roles: {q.id}")
        for identity in required_ids | set(a.optional_ids):
            if prohibited(memories[identity], q) is not None:
                raise ValueError(f"Required/optional fact is inaccessible: {q.id}")
        restriction_key = (q.world_id, q.actor_id, q.contact_id, q.timestamp)
        if restriction_key not in restriction_cache:
            restriction_cache[restriction_key] = {m.id for m in worlds[q.world_id] if prohibited(m, q) is not None}
        banned = restriction_cache[restriction_key]
        if not banned <= set(a.forbidden):
            raise ValueError(f"Oracle omits access/state restrictions: {q.id}")
        for identity, reason in a.forbidden.items():
            if reason not in ("access", "forgotten", "obsolete") or memories[identity].world_id != q.world_id:
                raise ValueError(f"Invalid forbidden fact: {q.id}")
        if (a.temporal_start is None) != (a.temporal_end is None):
            raise ValueError(f"Partial temporal window: {q.id}")
        if a.temporal_start is not None and a.temporal_end is not None:
            temporal_cases += 1
            start, end = instant(a.temporal_start), instant(a.temporal_end)
            if start >= end:
                raise ValueError(f"Empty temporal window: {q.id}")
            for g in a.required:
                if g.facet in ("yesterday", "gift_yesterday", "last_week"):
                    for identity in g.any_of:
                        event = memories[identity].event_start
                        if event is None or not start <= instant(event) < end:
                            raise ValueError(f"Event outside oracle window: {q.id}")
    if any(len(splits) != 1 for splits in partitions.values()):
        raise ValueError("A setting crosses evaluation partitions")
    if set(worlds) != {q.world_id for q in corpus.queries}:
        raise ValueError("Worlds without queries")
    if len(coverage) != len(worlds) * len(FAMILIES) * len(LANGUAGES) or set(coverage.values()) != {2}:
        raise ValueError("Incomplete family/language/paraphrase coverage")
    return {"valid": True, "synthetic": True, "memories": len(memories), "queries": len(queries),
            "worlds": len(worlds), "profiles": len(partitions), "families": len(FAMILIES),
            "temporal_cases": temporal_cases, "domains": dict(Counter(q.domain for q in corpus.queries))}
