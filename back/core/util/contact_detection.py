"""Offline extraction of contact coordinates, without identity attribution or effects."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache
import re
from typing import Literal
import unicodedata

from email_validator import EmailNotValidError, validate_email
import phonenumbers
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .countries import country_from_localization
from .contact_keys import normalize_contact_coordinate


class DetectedContactInfo(BaseModel):
    """One literal span in the scanned text; offsets use Python string indices."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    type: Literal["email", "phone", "postal_address", "instant_messaging"]
    value: str = Field(min_length=1)
    normalized_value: str = Field(min_length=1)
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    country: str | None = None
    platform: str | None = None

    @model_validator(mode="after")
    def consistent_span(self) -> DetectedContactInfo:
        if self.end - self.start != len(self.value):
            raise ValueError("The coordinate span must match the literal value length.")
        return self


_EMAIL = re.compile(r"(?<![\w.!#$%&'*+/=?^`{|}~@\-])[\w.!#$%&'*+/=?^`{|}~\-]+@(?:[\w\-]+\.)+[\w\-]+", re.UNICODE)
_URL = re.compile(r"(?:https?://|(?<![\w@])(?:t\.me|telegram\.me|wa\.me|signal\.me|matrix\.to|discord\.com)/)[^\s<>\"']+", re.IGNORECASE)
_MATRIX = re.compile(r"(?<![\w@])@[\w.=/\-]+:[\w.\-]+(?::\d{1,5})?", re.UNICODE)
_IM_LABEL = re.compile(
    r"\b(?P<platform>telegram|signal|discord|matrix|whatsapp|one_?bot|nextcloud(?:[ \t]+talk)?)"
    r"[ \t]*(?::|=|est\b|is\b)[ \t]*(?P<identity>\+?\d[\d ().\-]*\d|@?[\w.+#:/=\-]+)", re.IGNORECASE,
)
_HANDLE = re.compile(
    r"\b(?:pseudo|identifiant|username|handle)[ \t]*(?::|=|est\b|is\b)?[ \t]*"
    r"(?P<identity>@[\w.\-]{2,64})", re.IGNORECASE,
)
_DIRECTIVES = frozenset({"@exec", "@plan", "@approve", "@high", "@standard", "@task"})
_FR_STREET = re.compile(
    r"\b\d{1,5}(?:[ \t]*(?:bis|ter|[A-Z]))?[ \t]+"
    r"(?:rue|avenue|av\.|boulevard|bd\.|chemin|route|impasse|allée|allee|place|quai|passage|voie|cours)"
    r"[ \t]+(?=[^\W\d_])", re.IGNORECASE,
)
_EN_STREET = re.compile(
    r"\b\d{1,5}[ \t]+(?:[^\W\d_][\w'’\-]*[ \t]+){1,6}"
    r"(?:street|road|lane|avenue|boulevard|drive|way|st\.|rd\.)(?=\W|$)", re.IGNORECASE,
)
_POSTAL_LABEL = re.compile(r"\b(?:adresse(?:[ \t]+postale)?|postal[ \t]+address|address)[ \t]*:[ \t]*", re.IGNORECASE)
_POSTCODE_CITY = re.compile(r"\b\d{4,6}[ \t]+[^\W\d_][\w'’\-]*(?:[ \t]+[\w'’\-]+){0,4}", re.UNICODE)
_ADDRESS_STOP = re.compile(r"[;!?\n]|(?<!\bav)(?<!\bbd)(?<!\bSt)(?<!\bRd)\.(?=\s|$)", re.IGNORECASE)
_NEWLINE = re.compile(r"[ \t]*\n[ \t]*")
_NEXT_FIELD = re.compile(
    r"(?:,[ \t]*|[ \t]+et[ \t]+)(?:e-?mail|tél(?:éphone)?|telephone|phone|mobile|telegram|signal|discord|whatsapp|contact)\b",
    re.IGNORECASE,
)
_ADDRESS_CONTINUATION = re.compile(
    r"^(?:\d{4,6}\s+\S|b[âa]t(?:iment)?\b|appartement\b|appt\b|étage\b|etage\b|apt\b|suite\b|floor\b)",
    re.IGNORECASE,
)
_PHONE_REFERENCE = re.compile(
    r"(?:facture|invoice|commande|order|siret|siren|iban|référence|reference|ref\.?|ticket)"
    r"[ \t]*(?:n[°ºo.]?|number|numéro|numero)?[ \t]*[:#=\-]?[ \t]*$", re.IGNORECASE,
)
_LINK_IDENTITIES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?P<id>[\w]+)(?:[/?#].*)?", re.I), "telegram"),
    (re.compile(r"(?:https?://)?(?:www\.)?discord(?:app)?\.com/users/(?P<id>\d+)(?:[/?#].*)?", re.I), "discord"),
    (re.compile(r"(?:https?://)?wa\.me/(?P<id>\d+)(?:[/?#].*)?", re.I), "whatsapp"),
    (re.compile(r"(?:https?://)?signal\.me/#p/(?P<id>\+\d+)", re.I), "signal"),
    (re.compile(r"(?:https?://)?matrix\.to/#/(?P<id>@[\w.=/\-]+:[\w.\-]+(?::\d+)?)(?:\?.*)?", re.I), "matrix"),
)


def _overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in spans)


def _messaging_key(identity: str, platform: str | None, country: str | None = None) -> str | None:
    if platform == "telegram":
        return identity.lstrip("@").casefold()
    if platform in {"signal", "whatsapp"} and re.fullmatch(r"\+?\d[\d ().\-]*\d", identity):
        try:
            return normalize_contact_coordinate("phone", identity if identity.startswith(("+", "0")) else "+" + identity,
                country=country)
        except ValueError:
            return None
    return identity


def _addresses(text: str) -> Iterator[tuple[int, int]]:
    starts = sorted({match.start() for pattern in (_FR_STREET, _EN_STREET)
        for match in pattern.finditer(text)})
    starts.extend(match.end() for match in _POSTAL_LABEL.finditer(text))
    starts = sorted(set(starts))
    covered_end = -1
    for index, start in enumerate(starts):
        if start < covered_end:
            continue
        end = min(len(text), start + 500)
        if index + 1 < len(starts):
            end = min(end, starts[index + 1])
        boundary = _ADDRESS_STOP.search(text, start, end)
        if boundary:
            end = boundary.start()
        field = _NEXT_FIELD.search(text, start, end)
        if field:
            end = field.start()
        candidate = text[start:end]
        if not (_FR_STREET.search(candidate) or _EN_STREET.search(candidate) or _POSTCODE_CITY.search(candidate)):
            continue
        # Join a bounded contiguous postal block, without consuming another person's details.
        for _ in range(3):
            newline = _NEWLINE.match(text, end)
            if newline is None:
                break
            next_start = newline.end()
            next_end = text.find("\n", next_start)
            next_end = min(next_end if next_end >= 0 else len(text), next_start + 200)
            next_line = text[next_start:next_end].strip()
            if not _ADDRESS_CONTINUATION.match(next_line) or _FR_STREET.search(next_line):
                break
            end = next_end
        while end > start and text[end - 1] in " \t\r,":
            end -= 1
        if end > start:
            covered_end = end
            yield start, end


def detect_contact_infos(text: str, *, default_country: str | None = None) -> list[DetectedContactInfo]:
    """Detect coordinates in one current message, with no DNS, database or LLM calls.

    Postal extraction deliberately recognizes bounded French/English street patterns and
    explicitly labeled postal blocks. It is not a universal address recognizer/geocoder.
    """
    found: list[DetectedContactInfo] = []
    occupied: list[tuple[int, int]] = []
    urls = list(_URL.finditer(text))
    url_spans = [(match.start(), match.end()) for match in urls]

    def add(kind: Literal["email", "phone", "postal_address", "instant_messaging"],
            start: int, end: int, normalized: str, *, platform: str | None = None,
            country: str | None = None) -> None:
        if _overlaps(start, end, occupied):
            return
        found.append(DetectedContactInfo(type=kind, value=text[start:end], normalized_value=normalized,
            start=start, end=end, platform=platform, country=country))
        occupied.append((start, end))

    for match in urls:
        raw = match.group().rstrip(".,;!?)")
        for pattern, platform in _LINK_IDENTITIES:
            identity = pattern.fullmatch(raw)
            if identity is not None:
                key = _messaging_key(identity["id"], platform, default_country)
                if key is not None:
                    add("instant_messaging", match.start(), match.start() + len(raw), key, platform=platform)
                break
    for match in _MATRIX.finditer(text):
        if _overlaps(match.start(), match.end(), url_spans):
            continue
        raw = match.group().rstrip(".,;")
        add("instant_messaging", match.start(), match.start() + len(raw), raw, platform="matrix")
    for match in _EMAIL.finditer(text) if "@" in text else ():
        if _overlaps(match.start(), match.end(), url_spans):
            continue
        try:
            email = validate_email(match.group(), check_deliverability=False)
        except EmailNotValidError:
            continue
        add("email", match.start(), match.end(), email.normalized.casefold())
    for pattern in (_IM_LABEL, _HANDLE):
        for match in pattern.finditer(text):
            start, end = match.span("identity")
            raw = match["identity"].rstrip(".,;")
            if (_overlaps(start, end, url_spans) or not any(char.isalnum() for char in raw)
                    or raw.casefold() in _DIRECTIVES):
                continue
            platform = match.groupdict().get("platform")
            if platform:
                platform = platform.lower().replace(" ", "_").replace("onebot", "one_bot")
            key = _messaging_key(raw, platform, default_country)
            if key is not None:
                add("instant_messaging", start, start + len(raw), key, platform=platform)
    for start, end in _addresses(text):
        add("postal_address", start, end, " ".join(unicodedata.normalize("NFKC", text[start:end]).split()),
            country=default_country)
    country = default_country if default_country in phonenumbers.SUPPORTED_REGIONS else None
    # Preserve offsets while accepting typographic spaces common in French messages.
    phone_text = text.translate({0x202F: 0x20, 0x2009: 0x20, 0xA0: 0x20})
    for match in phonenumbers.PhoneNumberMatcher(phone_text, country, leniency=phonenumbers.Leniency.POSSIBLE):
        if _overlaps(match.start, match.end, url_spans) or _PHONE_REFERENCE.search(text[max(0, match.start - 50):match.start]):
            continue
        normalized = phonenumbers.format_number(match.number, phonenumbers.PhoneNumberFormat.E164)
        if match.number.extension:
            normalized += f";ext={match.number.extension}"
        add("phone", match.start, match.end, normalized,
            country=phonenumbers.region_code_for_number(match.number) or country)
    return sorted(found, key=lambda item: (item.start, item.end))


@lru_cache(maxsize=1)
def prepare_contact_detection() -> None:
    """Load offline metadata and parser caches before accepting the first message."""
    country_from_localization("FR")
    phonenumbers.PhoneMetadata.load_all()
    # Exercise lazily compiled email/number parsers without DNS, I/O or side effects.
    detect_contact_infos("warmup@example.org ; +33 1 23 45 67 89 ; +44 7700 900123", default_country="FR")
