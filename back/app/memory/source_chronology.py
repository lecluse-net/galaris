"""Evidence about when a source was written, sent or completed, and what year it covers."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re
from typing import Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, String, and_, case, cast, func, literal_column, type_coerce
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.sql import SQLColumnExpression
from sqlalchemy.sql.elements import ColumnElement, Grouping

from core.util import local_timezone_name

from .relevance import STOPWORDS, fold
from .temporal import MemoryTemporalAnchor


DateOrigin = Literal["title", "mail_date"]
_YEAR = r"(?:18|19|20|21)[0-9]{2}"
_MONTHS = {
    name: number for number, pair in enumerate((
        ("janvier", "january"), ("fevrier", "february"), ("mars", "march"), ("avril", "april"),
        ("mai", "may"), ("juin", "june"), ("juillet", "july"), ("aout", "august"),
        ("septembre", "september"), ("octobre", "october"), ("novembre", "november"), ("decembre", "december"),
    ), 1) for name in pair
}
_DATE_LABEL = r"(?<![a-z0-9_])(?:redigee?|publiee?|datee?|ecrit(?:e)?|written|published|date du document)(?:\s+(?:le|on))?\s*:?\s+"
_ISO = rf"({_YEAR})-([0-9]{{2}})-([0-9]{{2}})"
_NAMED = rf"([0-9]{{1,2}})\s+({'|'.join(_MONTHS)})\s+({_YEAR})"
_DAY_FIRST = rf"([0-9]{{1,2}})/([0-9]{{1,2}})/({_YEAR})"
# Unlabelled ISO dates are evidence when used as a leading dateline.
_TITLE_DATE = rf"(?:^\s*{_ISO}|{_DATE_LABEL}(?:{_ISO}|{_NAMED}|{_DAY_FIRST}))(?![a-z0-9/]|-[0-9])"
_YEAR_TOKEN = rf"(?<![a-z0-9/_-])({_YEAR})(?![a-z0-9/_-])"
_PERIOD_LABEL = r"^\s*(?:bilan|budget|rapport annuel|annual report|annual review|comptes annuels|synthese annuelle)(?=\s|$)"
_TITLE_SUFFIX = rf"(?:\s+[—–|-]\s+|{_DATE_LABEL}).*$"
_OPERATORS = re.compile(r'["«»“”]|\bOR\b|(?:^|\s)-', re.IGNORECASE)
_RECORDING = re.compile(r"\b(?:recemment\s+(?:indexe|importe|enregistre)|recently\s+(?:indexed|imported|recorded))\b")
_EXPLICIT_YEAR = re.compile(rf"\b(?:(?:redige[es]*|publie[es]*|ecrit[es]*)\s+en|(?:written|published)\s+in|(?:au sujet de|sur|pour|de|en|from|in|about|for))\s+({_YEAR})\b")
_RELATIVE = re.compile(r"\b(?:(?:la )?semaine derniere|semaine precedente|last week|previous week|cette semaine|this week|"
                       r"l['’]annee derniere|annee precedente|last year|cette annee|this year|"
                       r"le mois dernier|mois precedent|last month|ce mois(?:-ci)?|this month)\b")
_RECENT = re.compile(r"\b(?:les plus recent(?:e)?s?|(?:the )?(?:latest|newest)|plus recent(?:e)?s?|recent(?:e)?s?)\b")
_LATEST_PERSONAL = re.compile(r"\b(?:mon|ma|mes|my)\s+dernier(?:e)?s?\b|\bmy\s+(?:last|latest)\b")
_FILLER = STOPWORDS | {"mes", "my", "chose", "choses", "truc", "trucs", "thing", "stuff", "ecrit", "ecrits", "retrouve", "find"}


@dataclass(frozen=True, slots=True)
class SourceChronology:
    source_date: date | None = None
    source_date_origin: DateOrigin | None = None
    covered_year: int | None = None
    mentioned_year: int | None = None
    event_date: date | None = None

    def metadata(self) -> dict[str, str | int | None]:
        return {
            "source_date": self.source_date.isoformat() if self.source_date else None,
            "source_date_origin": self.source_date_origin,
            "covered_year": self.covered_year,
            "mentioned_year": self.mentioned_year,
            "event_date": self.event_date.isoformat() if self.event_date else None,
        }


@dataclass(frozen=True, slots=True)
class SourceTimeQuery:
    query: str
    start: date | None
    end: date
    dimension: Literal["source", "event_or_source", "coverage", "historical_year"]

    def metadata(self) -> dict[str, str | None]:
        return {"start": self.start.isoformat() if self.start else None, "end_exclusive": self.end.isoformat(),
                "dimension": self.dimension, "timezone": local_timezone_name()}

    def rank_date(self, evidence: SourceChronology) -> date | None:
        if self.dimension == "coverage":
            dates = (_year_start(evidence.covered_year),)
        elif self.dimension == "historical_year":
            dates = (evidence.source_date, _year_start(evidence.covered_year), _year_start(evidence.mentioned_year))
        elif self.dimension == "event_or_source":
            dates = (evidence.event_date, evidence.source_date)
        else:
            dates = (evidence.source_date,)
        return max((value for value in dates if value is not None and value < self.end
                    and (self.start is None or value >= self.start)), default=None)

    def sql_date(self, *, written: SQLColumnExpression[date],
                 coverage: SQLColumnExpression[date], mentioned: SQLColumnExpression[date],
                 event: SQLColumnExpression[date]) -> ColumnElement[date]:
        if self.dimension == "coverage":
            dates = (coverage,)
        elif self.dimension == "historical_year":
            dates = (written, coverage, mentioned)
        elif self.dimension == "event_or_source":
            dates = (event, written)
        else:
            dates = (written,)
        bounded = [case((value < self.end if self.start is None else and_(value >= self.start, value < self.end), value))
                   for value in dates]
        return bounded[0] if len(bounded) == 1 else func.greatest(*bounded, type_=Date())


def _year_start(year: int | None) -> date | None:
    return date(year, 1, 1) if year is not None else None


def _single_year(text: str) -> int | None:
    matches = re.findall(_YEAR_TOKEN, text)
    return int(matches[0]) if len(matches) == 1 else None


def _date_from_title(text: str) -> date | None:
    matches = list(re.finditer(_TITLE_DATE, text))
    if len(matches) != 1:
        return None
    leading_year, leading_month, leading_day, iso_year, iso_month, iso_day, named_day, month, named_year, numeric_day, numeric_month, numeric_year = matches[0].groups()
    try:
        return date(int(leading_year or iso_year or named_year or numeric_year),
                    int(leading_month or iso_month or numeric_month or _MONTHS[month]),
                    int(leading_day or iso_day or named_day or numeric_day))
    except ValueError:
        return None


def chronology_from_title(title: str, *, source_date: date | None = None, origin: DateOrigin | None = None,
                          event_date: date | None = None) -> SourceChronology:
    text = fold(title)
    written = source_date or _date_from_title(text)
    covered = _single_year(re.sub(_TITLE_SUFFIX, "", text)) if re.match(_PERIOD_LABEL, text) else None
    mentioned = _single_year(text) if written is None and covered is None else None
    return SourceChronology(written, (origin if source_date else "title") if written else None, covered, mentioned, event_date)


def memory_chronology(title: str, anchor: MemoryTemporalAnchor | None) -> SourceChronology:
    event_date = (date(anchor.year, anchor.month, anchor.day) if anchor is not None
                  and anchor.year is not None and anchor.month is not None and anchor.day is not None else None)
    return chronology_from_title(title, event_date=event_date)


def _date_sql(value: SQLColumnExpression[str]) -> ColumnElement[date]:
    return case((func.pg_input_is_valid(value, "date"), cast(value, Date())))


def _date_parts_sql(year: SQLColumnExpression[str], month: SQLColumnExpression[str],
                    day: SQLColumnExpression[str]) -> ColumnElement[date]:
    value = func.concat(year, "-", func.lpad(month, 2, "0"), "-", func.lpad(day, 2, "0"), type_=String())
    return case((and_(year.is_not(None), month.is_not(None), day.is_not(None)), _date_sql(value)))


def title_dates_sql(title: SQLColumnExpression[str]) -> tuple[ColumnElement[date], ColumnElement[date], ColumnElement[date]]:
    """SQL equivalent of the bounded title evidence, applied before candidate limits."""
    normalized = func.lower(func.normalize(title, literal_column("NFKC")))
    text = func.translate(normalized, "àâäçéèêëîïôöùûü", "aaaceeeeiioouuu", type_=String())
    parts = type_coerce(Grouping(func.regexp_match(text, _TITLE_DATE)), ARRAY(String()))
    year = func.coalesce(parts[1], parts[4], parts[9], parts[12], type_=String())
    month_name = case({name: str(number) for name, number in _MONTHS.items()}, value=parts[8])
    month = func.coalesce(parts[2], parts[5], parts[11], month_name, type_=String())
    day = func.coalesce(parts[3], parts[6], parts[7], parts[10], type_=String())
    written = case((func.regexp_count(text, _TITLE_DATE) == 1, _date_parts_sql(year, month, day)))
    period_title = func.regexp_replace(text, _TITLE_SUFFIX, "", type_=String())
    covered = case((and_(text.bool_op("~")(_PERIOD_LABEL), func.regexp_count(period_title, _YEAR_TOKEN) == 1),
                    _year_sql(period_title)))
    mentioned = case((and_(written.is_(None), covered.is_(None), func.regexp_count(text, _YEAR_TOKEN) == 1), _year_sql(text)))
    return written, covered, mentioned


def _year_sql(title: SQLColumnExpression[str]) -> ColumnElement[date]:
    return cast(func.concat(func.substring(title, _YEAR_TOKEN), "-01-01"), Date())


def anchored_event_date_sql(year: ColumnElement[int], month: ColumnElement[int], day: ColumnElement[int]) -> ColumnElement[date]:
    """Use explicit single calendar dates, leaving partial and recurring anchors to Calendar."""
    return _date_parts_sql(cast(year, String()), cast(month, String()), cast(day, String()))


def local_source_date(value: datetime) -> date | None:
    return value.astimezone(ZoneInfo(local_timezone_name())).date() if value.utcoffset() is not None else None


def local_source_date_sql(value: SQLColumnExpression[datetime]) -> ColumnElement[date]:
    return cast(func.timezone(local_timezone_name(), value), Date())


def mail_source_date_sql(value: ColumnElement[str]) -> ColumnElement[date]:
    return case((func.pg_input_is_valid(value, "timestamp with time zone"),
                 local_source_date_sql(cast(value, DateTime(timezone=True)))))


def _relative_period(label: str, today: date) -> tuple[date, date]:
    if "week" in label or "semaine" in label:
        start = today - timedelta(days=today.weekday())
        return (start, start + timedelta(days=7)) if label in {"cette semaine", "this week"} else (start - timedelta(days=7), start)
    if "month" in label or "mois" in label:
        start = today.replace(day=1)
        return (start, (start + timedelta(days=32)).replace(day=1)) if label.startswith(("ce ", "this ")) else ((start - timedelta(days=1)).replace(day=1), start)
    start = date(today.year, 1, 1)
    return (start, date(today.year + 1, 1, 1)) if label in {"cette annee", "this year"} else (date(today.year - 1, 1, 1), start)


def parse_source_time_query(query: str, *, today: date | None = None) -> SourceTimeQuery | None:
    if _OPERATORS.search(query):
        return None
    text = fold(query)
    if _RECORDING.search(text):
        return None
    explicit = list(_EXPLICIT_YEAR.finditer(text))
    relative = list(_RELATIVE.finditer(text))
    personal_latest = _LATEST_PERSONAL.search(text)
    recent = [personal_latest] if personal_latest is not None else list(_RECENT.finditer(text))
    # A compound date question needs its own comparison semantics.
    matches = [*explicit, *relative, *recent]
    if len(matches) != 1:
        return None
    match = matches[0]
    today = today or datetime.now(ZoneInfo(local_timezone_name())).date()
    dimension: Literal["source", "event_or_source", "coverage", "historical_year"] = "source"
    if explicit:
        year = int(match[1])
        start, end = date(year, 1, 1), date(year + 1, 1, 1)
        if match[0].startswith(("au sujet de ", "sur ", "pour ", "about ", "for ")):
            dimension = "coverage"
        elif match[0].split()[0] in {"de", "en", "from", "in"}:
            dimension = "historical_year"
    elif relative:
        start, end = _relative_period(match[0], today)
        dimension = "event_or_source"
    else:
        start = None if personal_latest is not None or match[0].startswith(
            ("les plus ", "plus ", "the ", "latest", "newest")) else today - timedelta(days=29)
        end = today + timedelta(days=1)
    remaining = text[:match.start()] + " " + text[match.end():]
    terms = re.findall(r"[^\W_]+(?:[-./][^\W_]+)*", remaining)
    return SourceTimeQuery(" ".join(term for term in terms if term not in _FILLER), start, end, dimension)
