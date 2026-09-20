"""Bounded long-term context prepared identically for every agent driver."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from core.params import runtime_settings

from .contracts import MemoryBrief, MemoryContextItem
from .facade import search_memory_detailed
from .metrics import observe_context
from .schemas import MemorySearchHit, MemoryType
from .service import record_llm_retrieval
from .retrieval import admit_recall_hits
from .schemas import MemoryRecallRequest


_HEADER = (
    "## Relevant long-term memory\n"
    "Use these already-retrieved governed notes when relevant; consult them before searching "
    "memory:// again. Preserve the cited memory identifiers."
)
_EXPERIENCE_HEADER = (
    "## Relevant prior experience\n"
    "Use these evidence-based lessons only when their applicability matches. Preserve their "
    "evidence references."
)
_MEMORY_POLICY = """
<durable-memory-policy>
Before acting, review any injected long-term-memory brief. If file_search is available, search
memory:// with semantic mode only when durable prior context could materially change the work:
a user preference or constraint, a prior decision, an ongoing project or Goal, a known procedure
or relationship, a useful past outcome, or an ambiguity that history could resolve. High-effort,
recurring, and long-running work requires this relevance check, not an automatic search.

Do not search when the request is self-contained, the injected brief is sufficient, or exact
current state belongs to an authoritative galaris:// business resource. Use one short query
centered on the relevant entity, decision, and constraint; use file_read on the exact
URI returned by search (memory:// or document://) only when an excerpt is insufficient. Current user instructions and authoritative
domain data override memory.

Use memory_remember when the current exchange establishes a lasting preference, fact, decision,
procedure, or relationship worth reusing; do not wait for an explicit request to remember it.
Do not store transient status, secrets, raw transcripts, provisional drafts or notes, or facts
already owned by an authoritative domain.

An explicit correction must be written first as the new durable memory, then the obsolete memory
must be forgotten. For an explicit erasure request, use the UUID when it is known; otherwise search
for the described memory and forget it only when the result identifies one item unambiguously.
Never guess which memory to erase.
</durable-memory-policy>
""".strip()
_GOAL_TITLE_RE = re.compile(
    r"(?:^|\n)\s*GOAL TITLE:\s*\n\s*([^\n]+)",
    flags=re.IGNORECASE,
)
_CYCLE_SUFFIX_RE = re.compile(
    r"\s*(?:[—–-]\s*)?cycle\s+\d+\s*$",
    flags=re.IGNORECASE,
)
_GENERIC_LABELS = frozenset(
    {
        "conversation",
        "new task",
        "nouvelle tâche",
        "task",
        "tâche",
        "untitled",
    }
)
_GENERIC_LABEL_PREFIXES = (
    "conversation —",
    "realtime voice conversation —",
)
_SPEAKER_PREFIX_RE = re.compile(r"(?m)^\s*\[[^\]\n]{1,100}\]\s*")
_MEMORY_QUERY_MAX_WORDS = 18
_MEMORY_QUERY_MAX_CHARS = 240
_SEMANTIC_HISTORY_MAX_MESSAGES = 2
_SEMANTIC_HISTORY_MESSAGE_MAX_CHARS = 600
_AUTOMATIC_MEMORY_TYPES: list[MemoryType] = [
    "core",
    "working",
    "episodic",
    "semantic",
    "procedural",
    "social",
]


def memory_policy_instructions() -> str:
    """Return the driver-neutral selective recall and capture policy."""

    return _MEMORY_POLICY


def _experience_confidence(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(str(value))))
    except (TypeError, ValueError):
        return 0.0


def _experience_evidence_count(value: object) -> int:
    try:
        return max(0, int(str(value)))
    except (TypeError, ValueError):
        return 0


def _bounded_query(value: str) -> str:
    normalized = " ".join(value.split())
    normalized = _CYCLE_SUFFIX_RE.sub("", normalized).strip(" \t-—–:;,")
    words = normalized.split()
    return " ".join(words[:_MEMORY_QUERY_MAX_WORDS])[
        :_MEMORY_QUERY_MAX_CHARS
    ].rstrip(" \t-—–:;,")


def _is_generic_label(value: str) -> bool:
    folded = value.casefold()
    return folded in _GENERIC_LABELS or any(
        folded.startswith(prefix) for prefix in _GENERIC_LABEL_PREFIXES
    )


def _without_speaker_prefixes(value: str) -> str:
    return " ".join(_SPEAKER_PREFIX_RE.sub("", value).split()).strip()


def _recent_history_text(
    conversation_history: Sequence[Mapping[str, object]],
) -> tuple[str, ...]:
    selected: list[str] = []
    for message in reversed(conversation_history):
        text = message.get("text")
        if not isinstance(text, str):
            continue
        normalized = _without_speaker_prefixes(text)
        if not normalized:
            continue
        role = str(message.get("role") or "message").strip().casefold()
        selected.append(
            f"{role}: {normalized[:_SEMANTIC_HISTORY_MESSAGE_MAX_CHARS]}"
        )
        if len(selected) >= _SEMANTIC_HISTORY_MAX_MESSAGES:
            break
    selected.reverse()
    return tuple(selected)


def memory_context_query(
    *,
    label: str,
    objective: str,
    contact_terms: tuple[str, ...] = (),
) -> str:
    """Derive a concise lexical query instead of AND-ing a complete task prompt."""

    goal_title = _GOAL_TITLE_RE.search(objective)
    if goal_title is not None:
        subject = _bounded_query(goal_title.group(1))
    else:
        bounded_label = _bounded_query(label)
        subject = (
            bounded_label
            if bounded_label and not _is_generic_label(bounded_label)
            else _bounded_query(_without_speaker_prefixes(objective))
        )
    contact = _bounded_query(" ".join(term for term in contact_terms if term))
    if not contact:
        return subject
    return _bounded_query(f"{contact} {subject}")


def memory_context_semantic_query(
    *,
    label: str,
    objective: str,
    conversation_history: Sequence[Mapping[str, object]] = (),
) -> str:
    """Keep the broad objective for embeddings while lexical recall stays concise."""

    normalized_label = " ".join(label.split()).strip()
    generic_label = _is_generic_label(normalized_label)
    normalized_objective = (
        _without_speaker_prefixes(objective)
        if generic_label
        else " ".join(objective.split()).strip()
    )
    if generic_label:
        parts = (
            normalized_objective,
            *_recent_history_text(conversation_history),
        )
    else:
        parts = (normalized_label, normalized_objective)
    combined = "\n".join(value for value in parts if value)
    # The request schema owns the absolute safety bound. The retrieval service
    # applies the live Params value, or its explicit per-call override.
    return combined[:4_000].strip()


async def build_memory_brief(
    *,
    agent_id: int,
    query: str,
    semantic_query: str | None = None,
    task_id: UUID | None = None,
    topic_item_id: UUID | None = None,
    contact_item_id: UUID | None = None,
    include_experience: bool = False,
    stage: Literal["planning", "execution"] = "execution",
    strict_contact_scope: bool = False,
    include_relevant: bool = True,
) -> MemoryBrief:
    """Retrieve, source, and render a deterministic context budget."""

    normalized = query.strip()
    if not runtime_settings.MEMORY_CONTEXT_ENABLED:
        return MemoryBrief(query=normalized, items=(), rendered="")

    limit = runtime_settings.MEMORY_CONTEXT_MAX_ITEMS
    relevant_page = None
    if normalized and include_relevant:
        relevant_page = await search_memory_detailed(
            normalized,
            agent_id=agent_id,
            semantic_query=semantic_query,
            limit=limit,
            memory_types=_AUTOMATIC_MEMORY_TYPES,
            task_id=task_id,
            memory_role="ordinary",
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
            strict_contact_scope=strict_contact_scope,
            exclude_agent_projections=True,
            record_llm_access=False,
            telemetry_kind="context",
        )

    general_hits: list[MemorySearchHit] = []
    truncated = False
    if relevant_page is not None:
        truncated = truncated or relevant_page.has_more
        general_hits.extend(relevant_page.hits)

    experience_hits: list[MemorySearchHit] = []
    experience_has_more = False
    if include_experience and normalized and include_relevant:
        experience_page = await search_memory_detailed(
            normalized,
            agent_id=agent_id,
            semantic_query=semantic_query,
            limit=min(runtime_settings.DREAM_EXPERIENCE_MAX_ITEMS, limit),
            memory_types=["episodic", "procedural"],
            task_id=task_id,
            memory_role="experience",
            topic_item_id=topic_item_id,
            contact_item_id=contact_item_id,
            strict_contact_scope=strict_contact_scope,
            record_llm_access=False,
            telemetry_kind=f"experience_{stage}",
        )
        experience_hits = list(experience_page.hits)
        experience_has_more = experience_page.has_more

    # The second search may await a provider after the first page was admitted.
    # Admit both pages together immediately before allocating the prompt budget.
    admitted = await admit_recall_hits(MemoryRecallRequest(
        agent_id=agent_id, query=normalized, topic_item_id=topic_item_id,
        contact_item_id=contact_item_id, strict_contact_scope=strict_contact_scope,
    ), [*general_hits, *experience_hits])
    admitted_by_id = {hit.item.id: hit for hit in admitted}
    general_hits = [admitted_by_id[hit.item.id] for hit in general_hits if hit.item.id in admitted_by_id]
    experience_hits = [admitted_by_id[hit.item.id] for hit in experience_hits if hit.item.id in admitted_by_id]
    reserved = min(len(experience_hits), runtime_settings.DREAM_EXPERIENCE_MAX_ITEMS, limit)
    experience_hits = experience_hits[:reserved]
    general_limit = max(0, limit - len(experience_hits))
    if len(general_hits) > general_limit:
        general_hits = general_hits[:general_limit]
        truncated = True

    def render_hits(
        hits: Sequence[MemorySearchHit],
        *,
        header: str,
        budget: int,
        experience: bool,
    ) -> tuple[str, list[MemoryContextItem], list[tuple[UUID, float]], bool]:
        rendered_parts = [header]
        consumed = len(header)
        items: list[MemoryContextItem] = []
        consulted: list[tuple[UUID, float]] = []
        local_truncated = False
        for hit in hits:
            refs = tuple(hit.source_refs)
            source_text = ", ".join(refs[:3]) if refs else "manual"
            node_kind = str(getattr(hit.item, "node_kind", "memory"))
            kind_text = f"; kind={node_kind}" if node_kind == "document" else ""
            experience_text = ""
            if experience:
                metadata = hit.item.metadata
                experience_text = (
                    f"; applicability={str(metadata.get('applicability') or 'unspecified')[:200]}"
                    f"; confidence={_experience_confidence(metadata.get('confidence')):.2f}"
                    f"; evidence={_experience_evidence_count(metadata.get('evidence_count'))}"
                )
            prefix = (
                f"\n\n- [{'document' if node_kind == 'document' else 'memory'}://{hit.item.id}] {hit.item.title} "
                f"(type={hit.item.memory_type}{kind_text}{experience_text}; source={source_text})\n  "
            )
            if node_kind == "document":
                revision = getattr(hit.item, "revision", None)
                passage = next(iter(getattr(hit, "passages", [])), None)
                location = f"; block_offset={passage.block_start}" if passage is not None and passage.block_start is not None else ""
                prefix = prefix.rstrip() + f" (revision={revision}{location})\n  "
            remaining = budget - consumed - len(prefix)
            if remaining <= 0:
                local_truncated = True
                break
            excerpt = hit.excerpt[:remaining]
            if len(excerpt) < len(hit.excerpt):
                excerpt = f"{excerpt[:-1].rstrip()}…" if excerpt else ""
                local_truncated = True
            block = prefix + excerpt
            rendered_parts.append(block)
            consumed += len(block)
            items.append(
                MemoryContextItem(
                    memory_id=str(hit.item.id),
                    title=hit.item.title,
                    excerpt=excerpt,
                    score=hit.score,
                    memory_type=hit.item.memory_type,
                    node_kind=node_kind,
                    source_refs=refs,
                    revision=getattr(hit.item, "revision", None),
                )
            )
            consulted.append((hit.item.id, hit.score))
            if consumed >= budget:
                local_truncated = True
                break
        return (
            "".join(rendered_parts) if items else "",
            items,
            consulted,
            local_truncated,
        )

    total_budget = runtime_settings.MEMORY_CONTEXT_MAX_CHARS
    experience_budget = min(runtime_settings.DREAM_EXPERIENCE_MAX_CHARS, total_budget)
    experience_rendered, experience_items, experience_consulted, exp_truncated = render_hits(
        experience_hits,
        header=_EXPERIENCE_HEADER,
        budget=experience_budget,
        experience=True,
    )
    separator_budget = 2 if experience_rendered and general_hits else 0
    general_budget = max(
        0,
        total_budget - len(experience_rendered) - separator_budget,
    )
    general_rendered, general_items, general_consulted, general_truncated = render_hits(
        general_hits,
        header=_HEADER,
        budget=general_budget,
        experience=False,
    )
    items = [*general_items, *experience_items]
    rendered = "\n\n".join(
        part for part in (general_rendered, experience_rendered) if part
    )
    truncated = truncated or experience_has_more or exp_truncated or general_truncated
    await record_llm_retrieval(
        agent_id=agent_id,
        item_scores=general_consulted,
        query=normalized,
        task_id=task_id,
        access_kind="context",
    )
    if experience_consulted:
        experience_access_kind: Literal[
            "experience_planning", "experience_execution"
        ] = (
            "experience_planning"
            if stage == "planning"
            else "experience_execution"
        )
        await record_llm_retrieval(
            agent_id=agent_id,
            item_scores=experience_consulted,
            query=normalized,
            task_id=task_id,
            access_kind=experience_access_kind,
        )
    brief = MemoryBrief(
        query=normalized,
        items=tuple(items),
        rendered=rendered,
        truncated=truncated,
    )
    observe_context(
        item_count=len(brief.items),
        prompt_chars=len(brief.rendered),
        truncated=brief.truncated,
    )
    return brief


__all__ = [
    "build_memory_brief",
    "memory_context_query",
    "memory_policy_instructions",
]
