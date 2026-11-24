"""Use the same evidence to compare authorized candidates from both search indexes."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re

from .relevance import fold, terms
from .reference_questions import parse_reference_question
from .source_chronology import SourceChronology, SourceTimeQuery, chronology_from_title
from .personal_records import personal_record_kind


_WINDOW = 16
_MAX_CANDIDATES = 500
_REFERENCE = re.compile(r"[^\W_]+(?:[-./][^\W_]+)*")
_DOCUMENT_KINDS = {
    "invoice": ("facture", "factures", "invoice", "invoices"),
    "quote": ("devis", "quotation", "quotations", "quote", "quotes"),
    "delivery": ("bon de livraison", "bons de livraison", "delivery note", "delivery notes"),
}


@dataclass(frozen=True, slots=True)
class FederatedEvidence:
    identity: str
    title: str
    excerpt: str
    passages: tuple[str, ...] = ()
    document_kind: str | None = None
    source_document: bool = False
    chronology: SourceChronology | None = None
    contact_match: bool = False


def federated_candidate_limit(offset: int, limit: int) -> int:
    """Fetch complete ranking windows so advancing a page cannot reorder its prefix."""
    return min(_MAX_CANDIDATES, ((offset + limit + _WINDOW) // _WINDOW) * _WINDOW)


def _phrase(text: str) -> str:
    return " ".join(re.findall(r"[^\W_]+", fold(text)))


def _references(text: str) -> set[str]:
    return {token for token in _REFERENCE.findall(fold(text))
            if any(char.isalpha() for char in token) and any(char.isdigit() for char in token)}


def rank_federated[T](query: str, memories: Sequence[T], resources: Sequence[T],
                      evidence: Callable[[T], FederatedEvidence], *, chronology: SourceTimeQuery | None = None) -> list[T]:
    """Rerank the bounded union, retaining source-local order when evidence ties."""
    phrase = _phrase(query)
    query_refs = _references(query)
    query_terms = set(terms(query))
    question = parse_reference_question(query)
    prefer_contact = personal_record_kind(query) is None
    requested = {kind for kind, aliases in _DOCUMENT_KINDS.items() if any(f" {alias} " in f" {phrase} " for alias in aliases)}

    def rank(candidate: FederatedEvidence, position: int) -> tuple[bool, int, bool, int, bool, bool, int, int, int]:
        title = _phrase(candidate.title)
        exact_refs = len(query_refs & _references(candidate.title)) if query_refs else 0
        title_kind = candidate.document_kind or next((kind for kind, aliases in _DOCUMENT_KINDS.items()
            if any(title == alias or title.startswith(f"{alias} ") for alias in aliases)), None)
        fragments = (candidate.excerpt, *candidate.passages)
        best_passage = max((len(query_terms.intersection(terms(part))) for part in fragments), default=0)
        return (bool(phrase) and phrase == title, exact_refs if candidate.source_document else 0,
                title_kind in requested, exact_refs, bool(phrase) and f" {phrase} " in f" {title} ",
                candidate.contact_match, best_passage, len(query_terms.intersection(terms(candidate.title))), -position)

    ranked: list[tuple[T, FederatedEvidence, int]] = []
    seen: set[str] = set()
    for start in range(0, max(len(memories), len(resources)), _WINDOW):
        batch: dict[str, tuple[T, FederatedEvidence, int]] = {}
        # Prefer source-owned passages to a duplicate projection in the same window.
        for stream in (resources, memories):
            for position, hit in enumerate(stream[start:start + _WINDOW]):
                description = evidence(hit)
                if question is not None and stream is memories and not question.has_evidence(
                    description.title, (description.excerpt, *description.passages)
                ):
                    continue
                if description.identity not in seen:
                    batch.setdefault(description.identity, (hit, description, position))
        ranked.extend(sorted(batch.values(), key=lambda entry: rank(entry[1], entry[2]), reverse=True))
        seen.update(batch)
    if chronology is not None:
        dated = [(prefer_contact and description.contact_match, source_date, hit) for hit, description, _ in ranked
                 if (source_date := chronology.rank_date(description.chronology or chronology_from_title(description.title))) is not None]
        dated.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        return [hit for _, _, hit in dated[:_MAX_CANDIDATES]]
    return [hit for hit, _, _ in ranked[:_MAX_CANDIDATES]]
