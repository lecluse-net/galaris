"""Bounded source passages and literal order references for the shared index."""

from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
import json
import re
from typing import Any, cast

from pydantic import JsonValue

from app.memory import redact_secrets

MAX_PASSAGES = 2_048
PASSAGE_CHARS = 1_200
_PASSAGE_OVERLAP = 180


@dataclass(frozen=True, slots=True)
class IndexedPassage:
    text: str
    locator: dict[str, Any] = field(default_factory=dict[str, Any])


def passages(text: str, **locator: Any) -> Iterator[IndexedPassage]:
    safe = redact_secrets(text.replace("\x00", ""))
    if not safe:
        return
    start = 0
    while start < len(safe):
        end = min(len(safe), start + PASSAGE_CHARS)
        if end < len(safe):
            boundary = max(safe.rfind("\n", start + 600, end), safe.rfind(" ", start + 600, end))
            if boundary > start:
                end = boundary
        part = safe[start:end]
        if part.strip():
            yield IndexedPassage(part, {**locator, "start": start, "end": end,
                "partial_start": start > 0 and safe[start - 1] != "\n", "partial_end": end < len(safe) and safe[end] != "\n"})
        if end == len(safe):
            break
        overlap = end - _PASSAGE_OVERLAP
        boundary = re.search(r"\s+", safe[overlap:end])
        start = overlap + boundary.end() if boundary is not None else overlap


def json_passages(raw: str) -> Iterator[IndexedPassage]:
    pending: list[tuple[str, JsonValue]] = [("", cast(JsonValue, json.loads(raw)))]
    while pending:
        location, value = pending.pop()
        if isinstance(value, dict) and value:
            pending.extend((f"{location}/{key.replace('~', '~0').replace('/', '~1')}", part)
                           for key, part in reversed(value.items()))
        elif isinstance(value, list) and value:
            pending.extend((f"{location}/{index}", value[index]) for index in range(len(value) - 1, -1, -1))
        else:
            rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            yield from passages(f"{location}: {rendered}" if location else rendered, json_pointer=location)


_COMMON_WORDS = frozenset("dans pour avec cette sont comme vous votre leur nous plus sans the that with from have this your will just".split())


def keywords(parts: Iterable[IndexedPassage]) -> list[str]:
    counts: Counter[str] = Counter()
    for passage in parts:
        counts.update(word for word in re.findall(r"[^\W\d_]{4,40}", passage.text.lower()) if word not in _COMMON_WORDS)
    return [word for word, _count in counts.most_common(12)]


@dataclass(frozen=True, slots=True)
class OrderEvidence:
    order: str
    issuer: str
    role: str
    reference: IndexedPassage
    issuer_reference: IndexedPassage


_ORDER = re.compile(r"(?im)^\s*(?:r[ée]f[ée]rence\s+(?:de\s+)?commande|(?:n[°o.]\s*(?:de\s+)?)?commande|purchase order|order (?:ref(?:erence)?|number))\s*[:#]\s*([A-Z0-9][A-Z0-9/-]{2,39})[ \t]*$")
_ISSUER = re.compile(r"(?im)^\s*(?:siret\s+(?:fournisseur|[ée]metteur)|supplier vat|issuer vat)\s*:\s*([A-Z0-9][A-Z0-9 ]{5,26})[ \t]*$")
_HEADING = re.compile(r"(?im)^\s*(devis|quotation|facture|invoice|bon de livraison|delivery note)(?:\s+(?:n[°o.]\s*)?[A-Z0-9-]+)?[ \t]*$")
_ROLE = {"devis": "quote", "quotation": "quote", "facture": "invoice", "invoice": "invoice",
         "bon de livraison": "delivery", "delivery note": "delivery"}
_CONTACT_LABEL = re.compile(
    r"(?im)^[ \t]*(client|destinataire|customer|bill to|recipient|patiente?|personne concern[ée]e|"
    r"titulaire|document holder|subject contact)(?:[ \t]+(?:e-?mail|courriel))?[ \t]*:[ \t]*([^\r\n]*)"
)
_CONTACT_ADDRESS = re.compile(
    r"[ \t]*(?:[^<>\n@]{0,120}<)?([a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,63})>?[ \t]*", re.IGNORECASE)
_CONTACT_ROLES = {"destinataire": "recipient", "recipient": "recipient", "client": "customer",
                  "customer": "customer", "bill to": "customer"}


def document_kind(parts: list[IndexedPassage]) -> str | None:
    roles = {_ROLE[match[1].lower()] for part in parts[:4] for match in _HEADING.finditer(_complete_lines(part))}
    return next(iter(roles)) if len(roles) == 1 else None


def _complete_lines(part: IndexedPassage) -> str:
    text = part.text
    if part.locator.get("partial_start"):
        text = text.partition("\n")[2]
    if part.locator.get("partial_end"):
        text = text.rpartition("\n")[0]
    return text


def contact_evidence(parts: list[IndexedPassage]) -> list[dict[str, Any]]:
    matches: dict[tuple[str, str | None], dict[str, Any]] = {}
    for part in parts:
        for match in _CONTACT_LABEL.finditer(_complete_lines(part)):
            role = _CONTACT_ROLES.get(match[1].lower(), "subject")
            email = _CONTACT_ADDRESS.fullmatch(match[2])
            address = email[1].casefold() if email is not None else None
            if role == "recipient" and address is None:
                continue
            matches.setdefault((role, address), {"role": role, "address": address, "locator": part.locator})
            if len(matches) >= 50:
                return [*matches.values(), {"role": "ambiguous", "address": None, "locator": part.locator}]
    return list(matches.values())


def order_evidence(parts: list[IndexedPassage], role: str | None) -> OrderEvidence | None:
    order = [(match[1].upper(), part) for part in parts for match in _ORDER.finditer(_complete_lines(part))]
    issuer = [(match[1].replace(" ", "").upper(), part) for part in parts for match in _ISSUER.finditer(_complete_lines(part))]
    if len({value for value, _part in order}) != 1 or len({value for value, _part in issuer}) != 1 or role is None:
        return None
    order_id, reference = order[0]
    issuer_id, issuer_reference = issuer[0]
    return OrderEvidence(order_id, issuer_id, role, reference, issuer_reference)
