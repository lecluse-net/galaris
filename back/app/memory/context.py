"""Bounded long-term context prepared identically for every agent driver."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from statistics import median
from collections.abc import Mapping, Sequence
from typing import Literal
from uuid import UUID

from core.params import runtime_settings
from core.util import search_terms

from .contracts import MemoryBrief, MemoryContextItem, MemorySearchItem
from .facade import search_memory_detailed
from .metrics import observe_context
from .schemas import MemorySearchHit
from .service import record_llm_retrieval
from .retrieval import admit_recall_hits
from .schemas import MemoryRecallRequest
from .passages import query_is_direct_contact_lookup, query_reference_ids, query_resource_references
from .relevance import matched_terms, resource_query_terms
from .source_chronology import SourceChronology, hit_chronology, parse_source_time_query
from .personal_records import personal_record_kind
from .question_evidence import parse_question_evidence
from .federated_ranking import FederatedEvidence, rank_federated


_HEADER = (
    "## Relevant long-term memory\n"
    "Review these already-retrieved governed notes. Search memory:// when a required fact "
    "is missing, ambiguous or truncated. Preserve the cited memory identifiers. These are retrieval candidates, "
    "not a proof that every requested fact is known. Check attribution, dates and conflicts; "
    "read the source when needed and state what remains unknown."
    " For chronology, source_date identifies the date supported by the source and event_date identifies "
    "an explicitly dated event. recorded_at describes when the memory was recorded."
)
_EXPERIENCE_HEADER = (
    "## Relevant prior experience\n"
    "Use these evidence-based lessons only when their applicability matches. Preserve their "
    "evidence references."
)
_MEMORY_POLICY = """
<durable-memory-policy>
Before acting, review any injected long-term-memory brief. For a resumed project or Goal,
a prior decision or commitment, a user preference or recurring constraint, an explicit
correction, a known relationship or procedure, identify the prior evidence needed for this
request. If that evidence is absent, ambiguous, conflicting or truncated and file_search is
available, search memory:// with mode="semantic" before answering or taking dependent action.
Do not assume that an automatically supplied brief covers every part of the request.
For a first-person request about a personal record, keep the subject and any date constraint
in tool queries. State when the evidence cannot establish that a record concerns the current person.

Do not search when the request is self-contained, all needed prior evidence is already present,
or exact current state belongs to an authoritative galaris:// business resource. Start with a
short query centered on the relevant entity, decision, and constraint. If it misses required
evidence, make up to two complementary searches with a reformulation or a missing subquestion;
do not repeat an unchanged query. Revisit prior experience after an unexpected failure or a
change of subject when history could resolve it. Use file_read on the exact
URI returned by search when an excerpt is insufficient. Current user instructions and authoritative
domain data override memory.

Use memory_remember sparingly: for an explicit request to remember, a correction to an existing
memory, or a confirmed, especially important fact whose immediate retention would materially
improve future decisions or prevent a significant recurring mistake. Spontaneous writes are
allowed, but should be rare. Being durable or potentially useful is not sufficient on its own.
Dream handles routine extraction from eligible conversations and tasks, checking for duplicates
before creating memories. Leave everyday observations, ordinary preferences, task completions,
and routine conclusions to Dream; do not turn memory writing into a per-turn or end-of-task step.
Before a warranted write, check the injected memories and, if needed and available, make one
targeted memory search. Skip an equivalent existing fact; do not store a paraphrase of it.
Do not store transient status, secrets, raw transcripts, provisional drafts or notes, or facts
already owned by an authoritative domain.
Write one independently retrievable and correctable fact per memory_remember call. Pass
fact={subject_ref,predicate,value} with one linked subject, one stable snake_case property and
one raw scalar value or {ref:URI}. If one assertion could change while another stays true, write
them in separate calls. For example, record report_day=friday and report_format=pdf separately.
Keep paragraphs and combined summaries out of memory, including out of the value field. Omit
subject_ref only for the current conversation contact or current agent. The server records
provenance and timestamps separately. A fact linked to a Contact or Document is still an
ordinary forgettable personal memory; only the direct source representation is protected.
Contact email addresses, phone numbers, postal addresses and messaging identifiers belong to
the structured Contacts directory. Its cards remain searchable memory resources. Never copy
their coordinates into a generic memory, even when asked to remember them. Contact discovery
handles new details separately; retain distinct preferences or decisions using the person's
name without repeating their coordinates.

Temporal anchors are optional. Supply year/month/day/weekday (ISO Monday=1), hour/minute
only when the fact explicitly warrants temporal recall. Unset components
are wildcards: month=9/day=27 means every September 27; hour=9 without minute means the whole
9 o'clock hour. Never default to today's date. Resolve relative dates from the source message's
timestamp in Galaris's configured timezone; ask when ambiguous. Upcoming memories convey information, not an
instruction to notify anyone. Use memory_upcoming to inspect further matches when truncated.
An anchor is a recall rule: outside its period the memory is excluded from automatic context;
when it matches it is added with priority independently of ordinary search criteria. Unanchored
memories continue through ordinary relevance search. Both branches preserve access and contact
isolation and share the context budget. A historical date can be the fact's value without an anchor.
Use anchors for intended time-based reminders, never just to timestamp a preference or fact.

An explicit correction must be written first as a new durable memory, with its subject,
corrected value and source attribution. Preserve the old evidence unless the user explicitly
requests its erasure; a changed fact over time is not automatically a false historical fact.
For a known personal memory, pass contradicts_memory_id and its current expected_revision to
memory_remember so the conflicting claims are linked. Reread a changed target before retrying.
Unresolved contradictory sources remain conflicting; do not decide solely by recency.
For an explicit erasure request, use the UUID when it is known; otherwise search
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
_MEMORY_QUERY_MAX_WORDS = 18
_MEMORY_QUERY_MAX_CHARS = 240
_SEMANTIC_HISTORY_MAX_MESSAGES = 2
_SEMANTIC_HISTORY_MESSAGE_MAX_CHARS = 600
_LEXICAL_HISTORY_SCAN_MESSAGES = 6
_CONVERSATIONAL_REFERENCE_RE = re.compile(
    r"\b(?:elle|elles|lui|eux|il|ils|son|sa|ses|leur|leurs|cela|ça|celui|celle|ceux|"
    r"she|he|her|his|they|them|their|it|that|those|this|previous|earlier)\b"
    r"|^(?:et\b|and\b|what about\b|how about\b|c['’]est\b)"
    r"|\b(?:tu peux me rappeler|can you remind me)\b",
    flags=re.IGNORECASE,
)
_TOPIC_RESET_RE = re.compile(
    r"^\s*(?:(?:bon|ok|okay|maintenant|now)[,;:.!\s]+)?"
    r"(?:autre sujet|nouveau sujet|on change de (?:sujet|dossier)|changeons de (?:sujet|dossier)|"
    r"new topic|different topic|switch (?:the )?topic|(?:let['’]s )?change (?:the )?(?:topic|files))\b",
    flags=re.IGNORECASE,
)
_ACKNOWLEDGEMENT_RE = re.compile(
    r"^\s*(?:oui|non|ok|okay|d['’]accord|merci|parfait|bien|yes|no|thanks|thank you|sure|great)"
    r"[\s.!?,;:…]*$", re.IGNORECASE,
)
_RETRY_RE = re.compile(r"\b(?:retry|again|réessayer|réessaie|recommence)\b", re.I)


def _needs_history(subject: str) -> bool:
    return (len(subject.split()) <= _MEMORY_QUERY_MAX_WORDS
            and not _TOPIC_RESET_RE.search(subject)
            and bool(_CONVERSATIONAL_REFERENCE_RE.search(subject) or _RETRY_RE.search(subject)))


def memory_policy_instructions() -> str:
    """Return the driver-neutral selective recall and capture policy."""

    return _MEMORY_POLICY


def _context_source_reference(reference: str) -> str:
    """Present native Tasks as readable URIs; retain opaque legacy receipts."""
    if reference.startswith("task:"):
        try:
            return f"galaris://task/{UUID(reference.removeprefix('task:').split(':', 1)[0])}"
        except ValueError:
            pass
    return reference


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
    references = query_resource_references(normalized)
    if references:
        for reference in references:
            normalized = normalized.replace(reference, " ")
        # Up to five whole UUID URIs fit in the existing 240-character budget.
        # Prose may be shortened; a half URI is not a usable identity anchor.
        normalized = " ".join((*references[:5], normalized))
    words = normalized.split()
    return " ".join(words[:_MEMORY_QUERY_MAX_WORDS])[
        :_MEMORY_QUERY_MAX_CHARS
    ].rstrip(" \t-—–:;,")


def _is_generic_label(value: str) -> bool:
    folded = value.casefold()
    return folded in _GENERIC_LABELS or any(
        folded.startswith(prefix) for prefix in _GENERIC_LABEL_PREFIXES
    )


_without_speaker_prefixes = search_terms.without_speaker_prefixes


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


def _continuity_subject(
    subject: str,
    conversation_history: Sequence[Mapping[str, object]],
) -> str:
    """Use recent human context as search terms for an unresolved reference.

    This is a retrieval hint, not evidence that a historical claim is true. A
    bounded scan avoids treating old conversations or assistant prose as the
    subject of the current human request.
    """
    if not _needs_history(subject):
        return ""
    for message in reversed(conversation_history[-_LEXICAL_HISTORY_SCAN_MESSAGES:]):
        if str(message.get("role") or "").strip().casefold() not in {"user", "human"}:
            continue
        text = message.get("text")
        if not isinstance(text, str):
            continue
        normalized = _without_speaker_prefixes(text)[:_SEMANTIC_HISTORY_MESSAGE_MAX_CHARS]
        if (normalized and normalized.casefold() != subject.casefold()
                and not _ACKNOWLEDGEMENT_RE.fullmatch(normalized)):
            return normalized
    return ""


def memory_context_query(
    *,
    label: str,
    objective: str,
    contact_terms: tuple[str, ...] = (),
    conversation_history: Sequence[Mapping[str, object]] = (),
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
        if not bounded_label or _is_generic_label(bounded_label):
            current = _without_speaker_prefixes(objective)
            # A spoken preamble can exhaust the lexical budget before the actual
            # question. Prefer the final explicit question when it stands alone.
            if len(current.split()) > _MEMORY_QUERY_MAX_WORDS and current.endswith("?"):
                question = re.split(r"(?<=[.!?])\s+", current)[-1]
                if len(search_terms.terms(question)) >= 2:
                    subject = _bounded_query(question)
            prior_subject = _continuity_subject(current, conversation_history)
            if prior_subject:
                subject = _bounded_query(f"{subject} {prior_subject}")
    contact = _bounded_query(" ".join(term for term in contact_terms if term))
    references = query_resource_references(objective)
    if references:
        subject = _bounded_query(" ".join((subject, *references)))
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
            *(_recent_history_text(conversation_history) if _needs_history(normalized_objective) else ()),
        )
    else:
        parts = (normalized_label, normalized_objective)
    combined = "\n".join(value for value in parts if value)
    # The request schema owns the absolute safety bound. The retrieval service
    # applies the live Params value, or its explicit per-call override.
    return combined[:4_000].strip()


def _render_chronology(evidence: SourceChronology | None) -> str:
    if evidence is None:
        return ""
    fields = ", ".join(f"{key}={value}" for key, value in evidence.metadata().items() if value is not None)
    return fields + "\n" if fields else ""


def _cited_passage(hit: MemorySearchHit, excerpt: str) -> MemorySearchHit:
    item = hit.item
    # A native title derived from the first characters of the body can
    # otherwise reintroduce another object's value above the selected quote.
    if item.node_kind == "memory" and not item.source_managed:
        item = item.model_copy(update={"title": excerpt[:120]})
    return hit.model_copy(update={"item": item, "excerpt": excerpt})


def _brief_evidence(hit: MemorySearchHit | MemorySearchItem) -> FederatedEvidence:
    if isinstance(hit, MemorySearchItem):
        return FederatedEvidence(identity=hit.uri, title=hit.title, excerpt=hit.excerpt,
            source_document=hit.node_kind in {"document", "file", "attachment"},
            chronology=hit.chronology, contact_match=hit.contact_match)
    item = hit.item
    document = item.node_kind == "document"
    uri = f"{'document' if document else 'memory'}://{item.id}"
    return FederatedEvidence(identity=uri, title=item.title, excerpt=hit.excerpt,
        passages=tuple(passage.excerpt for passage in hit.passages), source_document=document,
        chronology=hit_chronology(hit))


def _lexical_anchor(hit: MemorySearchHit, subject: frozenset[str], common: frozenset[str]) -> bool:
    """Keep a distinctive lexical hit across inflections, typos and languages."""
    if not any(source.endswith("_lexical") for source in hit.retrieval_sources):
        return False
    content = " ".join((hit.item.title, *hit.item.keywords, hit.excerpt))
    matched = matched_terms(content, subject)
    return (len(matched) >= 2 or any(len(term) >= 4 or term.isdigit() for term in matched - common))


_OTHER_AGENT = r"(?:(?:un|l['’])\s*autre agent|(?:another|the other) agent)"
_PRIVATE_NOTE = r"(?:une? (?:note privee|souvenir prive)|a private (?:note|memory))"
_SOURCE_TOPIC = r"(?:\s+(?:sur|concernant|au sujet de|about|regarding) [\w '’\-]{1,120})?"
_FOREIGN_NOTE_REQUEST = re.compile(
    r"(?:(?:retrouve|montre(?:-moi)?|donne(?:-moi)?|find|show me|give me|retrieve)\s+"
    r"(?:(?:la note reservee|le souvenir reserve) a (?:un autre|l['’]autre) agent"
    r"|(?:the )?(?:note|memory) restricted to " + _OTHER_AGENT
    + r"|(?:the other|another) agent['’]s private (?:note|memory)"
    r"|(?:la note privee|le souvenir prive) (?:d['’]un autre|de l['’]autre) agent)" + _SOURCE_TOPIC
    + r"|" + _OTHER_AGENT + r" (?:a|aurait|has) " + _PRIVATE_NOTE + _SOURCE_TOPIC
    + r"\s*[,;.]\s*(?:peux-tu (?:la|le) retrouver|can you (?:find|retrieve) it))\s*[?.!]*"
)


def _requests_other_agents_private_note(text: str) -> bool:
    # Only a request for that source alone has no admissible substitute. Keep
    # policy questions, quoted requests and explicit alternative sources searchable.
    folded = search_terms.fold(text.strip())
    return (not re.search(r"\b(?:et|ou|mais|sinon|and|or|but|instead|except|sauf|copie|copy|shared|partagee?)\b", folded)
            and _FOREIGN_NOTE_REQUEST.fullmatch(folded) is not None)


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
    conversational: bool = False,
) -> MemoryBrief:
    """Retrieve, source, and render a deterministic context budget."""

    normalized = query.strip()
    if (not runtime_settings.MEMORY_CONTEXT_ENABLED
            or conversational and _requests_other_agents_private_note(semantic_query or normalized)):
        return MemoryBrief(query=normalized, items=(), rendered="")

    limit = runtime_settings.MEMORY_CONTEXT_MAX_ITEMS
    chronology = parse_source_time_query(normalized)
    relevant_page = None
    if normalized and include_relevant:
        relevant_page = await search_memory_detailed(
            normalized,
            agent_id=agent_id,
            semantic_query=semantic_query,
            limit=limit,
            exclude_temporal=chronology is None,
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
    # Dated memories are presented once through the common agenda context.
    if relevant_page is not None:
        truncated = truncated or relevant_page.has_more
        seen = {hit.item.id for hit in general_hits}
        general_hits.extend(hit for hit in relevant_page.hits if hit.item.id not in seen)

    experience_hits: list[MemorySearchHit] = []
    experience_has_more = False
    if include_experience and normalized and include_relevant:
        experience_page = await search_memory_detailed(
            normalized,
            agent_id=agent_id,
            semantic_query=semantic_query,
            limit=min(runtime_settings.DREAM_EXPERIENCE_MAX_ITEMS, limit),
            exclude_temporal=True,
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

    indexed: list[MemorySearchItem] = []
    from .indexed_resources import resource_search

    if resource_search is not None and normalized and limit:
        indexed = await resource_search(MemoryRecallRequest(agent_id=agent_id, query=normalized, task_id=task_id,
            limit=limit, topic_item_id=topic_item_id, contact_item_id=contact_item_id,
            strict_contact_scope=strict_contact_scope or personal_record_kind(normalized) is not None,
            contextual_resources=True), mode="text")

    # Admit the private pages together after the additional search has finished.
    admitted = await admit_recall_hits(MemoryRecallRequest(
        agent_id=agent_id, query=normalized, topic_item_id=topic_item_id,
        contact_item_id=contact_item_id, strict_contact_scope=strict_contact_scope,
    ), [*general_hits, *experience_hits])
    admitted_by_id = {hit.item.id: hit for hit in admitted}
    general_hits = [admitted_by_id[hit.item.id] for hit in general_hits if hit.item.id in admitted_by_id]
    question = (parse_question_evidence(normalized, dated=chronology is not None)
                if conversational and (chronology is None or chronology.dimension == "event_or_source") else None)
    semantic_floor = 0.75
    if conversational and chronology is None:
        subject = frozenset(search_terms.terms(resource_query_terms(normalized)))
        references = set(query_reference_ids(normalized))
        common = search_terms.common_terms(hit.item.title for hit in general_hits)
        similarities = [hit.semantic_similarity for hit in general_hits if hit.semantic_similarity is not None]
        # Some models give even unrelated passages high cosine scores. In a
        # populated neighbourhood a semantic-only hit must also stand out.
        semantic_floor = max(0.75, median(similarities) + 0.04) if len(similarities) >= 4 else 0.75
        direct_contact = query_is_direct_contact_lookup(normalized)
        # Automatic injection can abstain. Explicit search retains the full ranked
        # page, including weaker neighbours that the caller can inspect.
        general_hits = [hit for hit in general_hits if (
            hit.item.id in references
            or (direct_contact and hit.item.id == contact_item_id)
            or "resolved_relation" in hit.retrieval_sources
            or (question is not None and question.source_language is not None)
            or (question is not None and (question.supports(hit.item.title, hit.excerpt)
                or any(question.supports(hit.item.title, p.excerpt) for p in hit.passages)))
            or _lexical_anchor(hit, subject, common)
            or search_terms.has_turn_evidence(subject, hit.item.title, hit.excerpt, common)
            or (bool(subject) and (hit.semantic_similarity or 0.0) >= semantic_floor)
        )]
    experience_hits = [admitted_by_id[hit.item.id] for hit in experience_hits if hit.item.id in admitted_by_id]
    reserved = min(len(experience_hits), runtime_settings.DREAM_EXPERIENCE_MAX_ITEMS, limit)
    experience_has_more = experience_has_more or len(experience_hits) > reserved
    experience_hits = experience_hits[:reserved]
    general_limit = max(0, limit - len(experience_hits))
    candidates: Sequence[MemorySearchHit | MemorySearchItem] = general_hits
    if indexed:
        candidates = rank_federated(normalized, candidates, indexed, _brief_evidence, chronology=chronology)
    if question is not None and (question.source_language is not None or question.storage is not None):
        source = question.source_language
        answer_hits: list[MemorySearchHit | MemorySearchItem] = []
        source_hits: list[MemorySearchHit | MemorySearchItem] = []
        semantic_hits: list[MemorySearchHit] = []
        for hit in candidates:
            if isinstance(hit, MemorySearchItem):
                if excerpt := question.answer_passage(hit.title, hit.excerpt):
                    answer_hits.append(replace(hit, excerpt=excerpt))
                elif source and (excerpt := source.passage(hit.title, hit.excerpt)):
                    source_hits.append(replace(hit, excerpt=excerpt))
                continue
            fragments = dict.fromkeys((hit.excerpt, *(part.excerpt for part in hit.passages)))
            tag = hit.item.metadata.get("language")
            excerpt = next((part for fragment in fragments if (part := question.answer_passage(
                hit.item.title, fragment, declared_language=tag))), "")
            if excerpt:
                answer_hits.append(_cited_passage(hit, excerpt))
                continue
            if source is None:
                continue
            if question.storage is not None and (excerpt := next((part for fragment in fragments
                    if (part := source.passage(hit.item.title, fragment, declared=tag))), "")):
                source_hits.append(_cited_passage(hit, excerpt))
            elif ((hit.semantic_similarity or 0.0) >= semantic_floor and hit.item.node_kind == "memory"
                  and len(hit.passages) == 1 and hit.passages[0].excerpt == hit.excerpt):
                # Only transfer semantic support to the same monolingual passage.
                # A cosine for a bilingual chunk cannot identify which half matched.
                part = source.passage(hit.item.title, hit.excerpt, declared=hit.item.metadata.get("language"), semantic=True)
                if part and part == hit.excerpt.strip():
                    semantic_hits.append(hit)
        if answer_hits or source is not None:
            candidates = answer_hits or source_hits or semantic_hits
    elif question is not None and question.single_detail:
        focused: list[MemorySearchHit | MemorySearchItem] = []
        for candidate in candidates:
            evidence = _brief_evidence(candidate)
            if question.supports(evidence.title, evidence.excerpt):
                focused.append(candidate)
            elif isinstance(candidate, MemorySearchHit):
                passage = next((p for p in candidate.passages if question.supports(evidence.title, p.excerpt)), None)
                if passage is not None:
                    focused.append(candidate.model_copy(update={"excerpt": passage.excerpt}))
                elif (question.attribute is None and not question.require_match
                      and (candidate.semantic_similarity or 0.0) >= semantic_floor
                      and question.same_subject(evidence.title + "\n" + evidence.excerpt)):
                    focused.append(candidate)
        if focused or question.require_match:
            candidates = focused
    truncated = truncated or len(candidates) > general_limit

    def render_hits(
        hits: Sequence[MemorySearchHit | MemorySearchItem],
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
        for position, hit in enumerate(hits):
            allowance = (budget - consumed) // (len(hits) - position)
            if isinstance(hit, MemorySearchItem):
                prefix = f"\n\n- [{hit.uri}] {hit.title}\n  "
                if allowance <= len(prefix):
                    local_truncated = True
                    continue
                text = _render_chronology(hit.chronology) + hit.excerpt
                excerpt = text[:allowance - len(prefix)]
                if len(excerpt) < len(text):
                    excerpt = excerpt[:-1].rstrip() + "…"
                    local_truncated = True
                rendered_parts.extend((prefix, excerpt))
                consumed += len(prefix) + len(excerpt)
                items.append(MemoryContextItem(
                    memory_id=str(hit.id), title=hit.title, excerpt=excerpt, score=0.8 if hit.contact_match else 0.5,
                    node_kind=hit.node_kind, source_refs=hit.source_refs, revision=hit.revision,
                    resource_uri=hit.uri, contact_match=hit.contact_match))
                continue
            refs = tuple(dict.fromkeys(_context_source_reference(ref) for ref in hit.source_refs))
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
                f"(source={source_text}{kind_text}{experience_text})\n  "
            )
            section_text = ""
            if node_kind == "document":
                revision = getattr(hit.item, "revision", None)
                # A stronger lexical window can replace the ranked passage. Use
                # the location and headings only for the excerpt they describe.
                passage = next((entry for entry in hit.passages if entry.excerpt == hit.excerpt), None)
                location = f"; block_offset={passage.block_start}" if passage is not None and passage.block_start is not None else ""
                prefix = prefix.rstrip() + f" (revision={revision}{location})\n  "
                if passage is not None and passage.section_path:
                    section_path = " > ".join(passage.section_path)
                    if len(section_path) > 300:
                        section_path = f"{section_path[:148]} … {section_path[-149:]}"
                    section_text = f"Section: {section_path}\n"
            remaining = allowance - len(prefix)
            if remaining <= 0:
                local_truncated = True
                continue
            conflict_text = ""
            conflicts = getattr(hit, "conflicts", ())
            if conflicts:
                conflict_text = "UNRESOLVED CONFLICT: " + "; ".join(
                    f"{conflict.uri} (recorded={conflict.recorded_at.isoformat()}, revision={conflict.revision}, "
                    f"sources={','.join(_context_source_reference(ref) for ref in conflict.source_refs[:2]) or 'manual'}): {conflict.excerpt}"
                    for conflict in conflicts
                ) + ". Do not choose a claim solely because it is newer.\n"
            recorded = getattr(hit.item, "created_at", None)
            recorded_text = f"recorded_at={recorded.isoformat()}\n" if isinstance(recorded, datetime) else ""
            validity = ", ".join(f"{key}={value.isoformat()}" for key in ("valid_from", "valid_until")
                if isinstance(value := getattr(hit.item, key, None), datetime))
            chronology = hit_chronology(hit)
            full_excerpt = (conflict_text + _render_chronology(chronology) + recorded_text
                            + (validity + "\n" if validity else "") + section_text + hit.excerpt)
            excerpt = full_excerpt[:remaining]
            if len(excerpt) < len(full_excerpt):
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
    overflow_note = ("\n\nMemory context is bounded: omitted evidence may still exist. Search memory:// "
                     "for missing facts. Dated memories are presented in the common agenda context.")
    total_budget = max(0, total_budget - len(overflow_note))
    experience_budget = min(runtime_settings.DREAM_EXPERIENCE_MAX_CHARS, total_budget)
    experience_rendered, experience_items, experience_consulted, exp_truncated = render_hits(
        experience_hits,
        header=_EXPERIENCE_HEADER,
        budget=experience_budget,
        experience=True,
    )
    general_budget = max(0, total_budget - len(experience_rendered) - (2 if experience_rendered else 0))
    general_rendered, general_items, general_consulted, general_truncated = render_hits(
        candidates[:general_limit],
        header=_HEADER,
        budget=general_budget,
        experience=False,
    )
    items = [*general_items, *experience_items]
    rendered = "\n\n".join(
        part for part in (general_rendered, experience_rendered) if part
    )
    truncated = truncated or experience_has_more or exp_truncated or general_truncated
    if truncated and items:
        rendered += overflow_note
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
