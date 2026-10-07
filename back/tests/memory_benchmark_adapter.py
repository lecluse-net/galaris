"""Real Galaris context adapter restricted to the ephemeral test database.

Fixture loading uses ORM snapshots, as other database integration tests do.
Search, ACL/validity admission, ranking, memory rendering and capsule composition
are real application calls. Only the embedding boundary and experiment seams are
replaced, locally to the pytest process. No answer labels enter retrieval.
"""

from __future__ import annotations

import asyncio
import hashlib
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from sqlalchemy import insert

from app.agent import context as agent_context
from app.agent.contracts import AgentContextRequest, AgentSnapshot
from app.agent.models import Agent, Title
from app.memory import access, admission, bootstrap, context as memory_context, goal_folders, library_queries, retrieval, service, source_access, storage
from app.memory.embedding import MemoryEmbeddingNotConfiguredError
from app.memory.models import MemoryContactItem, MemoryItem, MemoryRevision, MemorySource
from app.memory.storage import NativeFileStorage, register_storage
from core.database import engine, get_db_session
from core.settings import settings
from core.user import UserModel
from core.util import local_timezone_name, visible_text
from scripts.memory_benchmark.experiments import Plan, entity_phrases, fold, plan
from scripts.memory_benchmark.generate import Memory, Query


@dataclass
class Trace:
    query: Query
    variant: str
    plan: Plan | None = None
    candidate_ids: list[str] = field(default_factory=list)
    retrieved_ids: list[str] = field(default_factory=list)
    upcoming_ids: list[str] = field(default_factory=list)
    searches: list[dict] = field(default_factory=list)
    excerpts: dict[str, str] = field(default_factory=dict)
    sql_count: int = 0


CURRENT: ContextVar[Trace | None] = ContextVar("benchmark_trace", default=None)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        trace = CURRENT.get()
        if trace is None:
            return datetime.now(tz)
        value = datetime.fromisoformat(trace.query.timestamp)
        return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)


def assert_isolated():
    if (settings.APP_ENV != "test" or settings.POSTGRES_HOST != "db-test" or settings.POSTGRES_DB != "test_db"
            or engine.url.host != "db-test" or engine.url.database != "test_db"):
        raise RuntimeError("Benchmark must run via make tests in the ephemeral database")


async def fixture_identity():
    assert_isolated()
    async with get_db_session() as db:
        user = UserModel(email=f"benchmark-{uuid5(NAMESPACE_URL, str(id(db)))}@example.invalid",
                         hashed_password="synthetic-not-a-login", display_name="Synthetic benchmark owner")
        title = Title(label="Synthetic benchmark role", gender="X")
        db.add_all([user, title])
        await db.flush()
        return user.id, title.id


def _write_resources(root, records):
    for identity, content in records:
        path = root / identity[:2] / identity
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


async def load_world(memories: tuple[Memory, ...], queries: tuple[Query, ...], root: Path,
                     *, user_id: int, title_id: int) -> AgentSnapshot:
    assert_isolated()
    actor = queries[0].actor_id
    actors = sorted({actor} | {a for m in memories for a in m.allowed_actor_ids})
    async with get_db_session() as db:
        agents = [Agent(user_id=user_id, title_id=title_id, first_name="Synthetic", last_name="Agent",
                        code=f"benchmark-{queries[0].world_id[:12]}-{i}", agent_driver="internal")
                  for i, _ in enumerate(actors)]
        db.add_all(agents)
        await db.flush()
        ids = {a: agent.id for a, agent in zip(actors, agents, strict=True)}
        peer = next(ids[a] for a in actors if a != actor)
        now = datetime.fromisoformat(queries[0].timestamp)
        rows, revisions, sources, contacts, resources = [], [], [], [], []
        for contact in sorted({q.contact_id for q in queries} | {m.contact_scope for m in memories if m.contact_scope}):
            content = b"<p>Synthetic contact boundary.</p>"
            identity = UUID(contact)
            rows.append(dict(id=identity, owner_agent_id=ids[actor], title="Synthetic contact boundary",
                             resource_id=contact, content_hash=hashlib.sha256(content).hexdigest(),
                              media_type="text/html", search_text="Synthetic contact boundary",
                             source_managed=True, managed_source_kind="messenger_contact", managed_source_ref=contact,
                             read_only=True, created_at=now, updated_at=now))
            resources.append((contact, content))
        for m in memories:
            content = m.content_html.encode("utf-8")
            digest = hashlib.sha256(content).hexdigest()
            identity = UUID(m.id)
            owner = ids[m.allowed_actor_ids[0]] if m.allowed_actor_ids else peer
            metadata = {"language": m.language, "event_start": m.event_start, "event_end": m.event_end,
                        "known_at": m.known_at}
            anchor = m.temporal_anchor
            if anchor is not None:
                # Source fixture zones describe an event; persisted anchors use Galaris's zone.
                instant = datetime.fromisoformat(m.event_start).astimezone(ZoneInfo(local_timezone_name()))
                anchor = {part: getattr(instant, part) for part in ('year', 'month', 'day', 'hour', 'minute')}
            rows.append(dict(id=identity, owner_agent_id=owner, title=m.title,
                             resource_id=m.id, provider_code="native",
                             media_type="text/html", content_profile_version=1, content_hash=digest,
                             size_bytes=len(content), search_text=visible_text(m.content_html), metadata_=metadata,
                             valid_from=datetime.fromisoformat(m.valid_from) if m.valid_from else None,
                             valid_until=datetime.fromisoformat(m.valid_until) if m.valid_until else None,
                             temporal=anchor, created_at=datetime.fromisoformat(m.recorded_at),
                             updated_at=datetime.fromisoformat(m.recorded_at),
                             deleted_at=datetime.fromisoformat(m.recorded_at) if m.state == "forgotten" else None))
            revisions.append(dict(item_id=identity, revision=1, provider_code="native", resource_id=m.id,
                                  content_hash=digest, content_type="text", media_type="text/html", title=m.title,
                                  content_profile_version=1, metadata_=metadata, temporal=anchor,
                                  created_at=datetime.fromisoformat(m.recorded_at)))
            sources.append(dict(id=UUID(m.source["id"]), item_id=identity, source_kind="synthetic-benchmark",
                                source_ref=m.source["id"], excerpt=m.source["text"], content_hash=digest,
                                created_at=datetime.fromisoformat(m.known_at)))
            resources.append((m.id, content))
            if m.contact_scope:
                contacts.append(dict(item_id=identity, owner_agent_id=owner, contact_item_id=UUID(m.contact_scope),
                                     source_kind="synthetic-benchmark", source_ref=m.source["id"]))
        await asyncio.to_thread(_write_resources, root, resources)
        await db.execute(insert(MemoryItem), rows)
        await db.execute(insert(MemoryRevision), revisions)
        await db.execute(insert(MemorySource), sources)
        if contacts:
            await db.execute(insert(MemoryContactItem), contacts)
        return AgentSnapshot(ids[actor], f"benchmark-{queries[0].world_id[:12]}", "Synthetic", "Agent", "internal")


def install_adapter(monkeypatch, root: Path, reference_sources: Path | None = None):
    assert_isolated()
    monkeypatch.setattr(storage, "_providers", {})
    register_storage(NativeFileStorage(root, max_bytes=1_000_000))
    monkeypatch.setattr(agent_context, "_providers", {})
    agent_context.register_context_provider("long_term_memory", bootstrap.memory_context_provider, priority=20)
    # Final admission independently rechecks validity. Every read-side clock
    # reached by the fixture must agree with the scenario, not the host date.
    for module in (retrieval, service, admission, goal_folders, library_queries, agent_context):
        monkeypatch.setattr(module, "datetime", FixedClock)
    real_rank = retrieval._weighted_rank
    real_search = memory_context.search_memory_detailed
    real_temporal = memory_context.temporal_hits
    previous = None
    previous_rank = None
    if reference_sources is not None:
        from tests.memory_benchmark_reference import load_reference
        previous = load_reference(reference_sources, FixedClock)
        previous_rank = previous['retrieval']._weighted_rank
        if 'access' in previous:
            real_structural_access = access._structural_access

            def structural_access(*args, **kwargs):
                trace = CURRENT.get()
                function = (previous['access']._structural_access
                            if trace is not None and trace.variant == 'previous'
                            else real_structural_access)
                return function(*args, **kwargs)

            # ACL consumers import the public predicate by value. Route its
            # structural helper per ContextVar so calendar, search and final
            # admission all use the same variant, including concurrent worlds.
            monkeypatch.setattr(access, '_structural_access', structural_access)
        if 'catalogue' in previous:
            real_catalogue_clause, reader = source_access._checks['file_catalogue']

            def catalogue_clause(*args, **kwargs):
                trace = CURRENT.get()
                function = (previous['catalogue'].catalogue_access_clause
                            if trace is not None and trace.variant == 'previous'
                            else real_catalogue_clause)
                return function(*args, **kwargs)

            monkeypatch.setitem(source_access._checks, 'file_catalogue', (catalogue_clause, reader))

    async def no_embedding():
        raise MemoryEmbeddingNotConfiguredError("Controlled lexical benchmark")

    if previous is not None:
        previous['retrieval'].resolve_embedding_model = no_embedding

    async def rank_observer(*args, **kwargs):
        trace = CURRENT.get()
        rank = previous_rank if trace is not None and trace.variant == 'previous' else real_rank
        ranked, sources = await rank(*args, **kwargs)
        if trace is not None:
            trace.candidate_ids.extend(str(i) for i in sources if str(i) not in trace.candidate_ids)
        return ranked, sources

    async def search_observer(text, **kwargs):
        trace = CURRENT.get()
        if trace is None:
            return await real_search(text, **kwargs)
        q = trace.query
        trace.plan = plan(trace.variant, message=q.message, history=tuple(h["text"] for h in q.history),
                          timestamp=q.timestamp, timezone=q.timezone, baseline_query=text)

        async def search(query, **overrides):
            attempt = {"query": query, "semantic_query": kwargs.get("semantic_query"),
                       "mode": "failed", "degraded": True, "reason": "search_failed"}
            trace.searches.append(attempt)
            try:
                search_function = previous['facade'].search_memory_detailed if trace.variant == 'previous' else real_search
                page = await search_function(query, **{**kwargs, **overrides})
            except Exception as error:
                attempt["reason"] = type(error).__name__
                raise
            attempt.update(mode=page.mode, degraded=page.degraded, reason=page.degradation_reason)
            trace.excerpts.update({str(h.item.id): h.excerpt for h in page.hits})
            return page

        primary = await search(trace.plan.lexical)
        if trace.variant in ("baseline", "previous"):
            trace.retrieved_ids = [str(h.item.id) for h in primary.hits]
            return primary
        entity_hits, dated_hits = [], []
        for entity in trace.plan.entities:
            page = await search(entity)
            matches = [h for h in page.hits if fold(h.item.title).startswith(fold(entity))]
            matches.sort(key=lambda h: h.item.metadata.get("language") != q.language)
            names = set()
            for hit in matches:
                key = fold(hit.item.title.split(" — ")[0])
                if key not in names:
                    entity_hits.append(hit)
                    names.add(key)
                if len(names) == 2:
                    break
            # An exact nickname hit can introduce a full name. Follow that
            # admitted evidence once; never consult an entity oracle/catalogue.
            nickname = next((h for h in matches if fold(h.item.title) == fold(entity)), None)
            if nickname is not None and len(entity.split()) == 1:
                introduced = next((value for value in entity_phrases(nickname.excerpt, (), limit=8)
                                   if len(value.split()) > 1 and fold(value) != fold(entity)), None)
                if introduced is not None:
                    followed = await search(introduced)
                    identities = [h for h in followed.hits if fold(h.item.title).startswith(fold(introduced))]
                    identities.sort(key=lambda h: h.item.metadata.get("language") != q.language)
                    entity_hits.extend(identities[:1])
        if trace.plan.window is not None:
            dates = " ".join(trace.plan.window.dates())
            page = await search(dates)
            for hit in page.hits:
                event = hit.item.metadata.get("event_start")
                if isinstance(event, str) and trace.plan.window.start <= datetime.fromisoformat(event) < trace.plan.window.end:
                    dated_hits.append(hit)
            terms = set(fold(trace.plan.lexical).split())
            dated_hits.sort(key=lambda h: (h.item.metadata.get("language") != q.language,
                                           -len(set(fold(h.item.title + " " + h.excerpt).split()) & terms), -h.score))
        # Bounded entity and time channels precede ordinary results. All entries
        # came through canonical search and its live ACL/validity admission.
        merged = []
        seen = set()
        for hit in [*entity_hits[:2], *dated_hits[:2], *primary.hits, *entity_hits[2:], *dated_hits[2:]]:
            if hit.item.id not in seen:
                merged.append(hit)
                seen.add(hit.item.id)
        merged = merged[:kwargs["limit"]]
        trace.retrieved_ids = [str(h.item.id) for h in merged]
        return primary.model_copy(update={"hits": merged, "has_more": primary.has_more or len(seen) > len(merged)})

    async def calendar_observer(*args, **kwargs):
        hits, more = await real_temporal(*args, **kwargs)
        trace = CURRENT.get()
        if trace is not None:
            trace.upcoming_ids = [str(h.item.id) for h in hits]
            if trace.plan is not None and trace.plan.relevant_first:
                available = max(0, kwargs["limit"] - len(trace.retrieved_ids))
                return hits[:available], more or len(hits) > available
        return hits, more

    monkeypatch.setattr(retrieval, "resolve_embedding_model", no_embedding)
    monkeypatch.setattr(retrieval, "_weighted_rank", rank_observer)
    if previous is not None:
        previous['retrieval']._weighted_rank = rank_observer
    monkeypatch.setattr(memory_context, "search_memory_detailed", search_observer)
    monkeypatch.setattr(memory_context, "temporal_hits", calendar_observer)


async def observe(query: Query, variant: str, agent: AgentSnapshot, db):
    import time

    trace = Trace(query, variant)
    token = CURRENT.set(trace)
    savepoint = await db.begin_nested()
    try:
        started = time.perf_counter()
        request = AgentContextRequest(task_id=None, agent=agent, label="Conversation", objective=query.message,
                                      messenger_connection_id=1, message_platform="synthetic", message_group_id=query.world_id,
                                      contact_memory_item_id=UUID(query.contact_id),
                                      fallback_history=tuple(query.history), task_data={"sender_is_ai": False})
        context = await agent_context.build_agent_run_context(request)
        latency = (time.perf_counter() - started) * 1000
        errors = {key: value for key, value in context.metadata.items() if key.endswith("_error")}
        selected = tuple(entry for entry in context.context_capsule.entries if entry.kind == "memory")
        injected = [entry.reference for entry in selected]
        observation = {"query_id": query.id, "candidates": trace.candidate_ids,
                       "retrieved": trace.retrieved_ids, "injected": injected, "latency_ms": latency}
        detail = {"query_id": query.id, "variant": variant, "searches": trace.searches,
                  "provider_errors": errors,
                  "upcoming_ids": trace.upcoming_ids, "sql_count": trace.sql_count,
                  "memory_context_chars": len(context.memory_context),
                  "memory_brief_chars": len(str(context.metadata.get("memory_context_rendered", ""))),
                  "capsule_chars": len(context.context_capsule.rendered),
                  "truncated": context.metadata.get("memory_context_truncated"),
                  "excerpts": {entry.reference: entry.excerpt for entry in selected}}
        return observation, detail
    finally:
        await savepoint.rollback()  # Reset usage counters, freshness and audit rows between cases.
        CURRENT.reset(token)
