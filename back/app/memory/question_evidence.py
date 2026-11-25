"""Bilingual passage evidence for bounded, single-detail conversational questions."""

from dataclasses import dataclass
import re

from .relevance import entity_groups, fold, matched_entities, resource_query_terms, terms
from .identity_attributes import IdentityAttribute, identity_attribute
from .source_language import SourceLanguage, source_language_query
from .storage_evidence import StorageLookup, storage_lookup


@dataclass(frozen=True, slots=True)
class Detail:
    question: re.Pattern[str]
    evidence: re.Pattern[str]


def _detail(question: str, evidence: str) -> Detail:
    return Detail(re.compile(r"\b(?:" + question + r")\b"), re.compile(r"\b(?:" + evidence + r")\b"))


_ACCESS_CODE = _detail(
    r"code d['’](?:entree|acces)|digicode|(?:door|entry|access) code|passcode",
    r"code d['’](?:entree|acces)|digicode|(?:door|entry|access) code|passcode|keypad|clavier numerique"
    r"|(?:porte|door|entree|entrance)\s*[:#–-]?\s*\d{3,10}"
    r"|(?:composez|tapez|saisissez|dial|type|key in)\s+\d{3,10}",
)
_PROCEDURE = _detail(
    r"procedures?|mode operatoire|etapes|instructions?|steps|marche a suivre"
    r"|comment (?:reprendre|proceder|demarrer)|how (?:do|should|can) (?:we|i) (?:resume|proceed|start)",
    r"procedures?|etapes?|steps?|instructions?|mode operatoire|workflow|mode d['’]emploi"
    r"|[a-z]{2,}(?:er|ir|re)\b[^.!?\n]{0,110}\b(?:puis|ensuite)\s+[a-z]{2,}(?:er|ir|re)"
    r"|first\b.{1,140}\bthen|(?:,\s*|and\s+)then\s+[a-z]+",
)
_REQUIREMENT = _detail(
    r"contraintes?|exigences?|requirements?|constraints?|preconditions?|prerequisites?|prerequis",
    r"contraintes?|exigences?|prerequis|preconditions?|prerequisites?|obligatoire|imperatif|requirements?"
    r"|constraints?|mandatory|requires?|required|must|(?:doit|doivent)\s+(?:etre\s+)?[a-z]{2,}(?:er|ir|re)",
)
_DISCUSSION = _detail(
    r"discut\w*|evoqu\w*|echang(?:e|es|er)|discuss\w*|spoke|talk(?:ed)? about|conversation",
    r"discut\w*|evoqu\w*|echang\w*|discuss\w*|spoke|talked|conversation|entretien",
)
_NUMBER = (
    r"(?:\d+(?:[.,]\d+)?|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|douze|vingt|trente|"
    r"quarante|cinquante|cent|two|three|four|five|seven|eight|nine|ten|twelve|twenty|thirty|"
    r"forty|fifty|hundred)"
)
_TIME_UNIT = r"(?:s|sec|secondes?|seconds?|min|minutes?|h|heures?|hours?|jours?|days?|semaines?|weeks?|mois|months?|ans?|years?)"
_DURATION = _detail(
    r"duree|combien de temps|duration|how long (?:until|before|(?:will|would|do|does|did)\b.{0,65}\btake)",
    _NUMBER + r"\s*" + _TIME_UNIT,
)
_QUANTITY = _detail(
    r"quantites?|combien de(?! temps\b)|quel nombre|how many|how much|what number|quantity|quantities",
    _NUMBER + r"[^\S\n]+(?!(?:a|au|de|du|des|en|et|est|pour|par|sur|and|at|for|from|in|is|of|on|or|to|was|with)\b)[^\W\d_]{2,}"
    r"|(?:quantite|quantity|nombre|count|total)\s*(?:[:=]|(?:est de|is))\s*" + _NUMBER,
)
_SCOPE = _detail(
    r"perimetre|scope|inclus(?:e?s?)?|ecart(?:e|es|ee|ees)|exclu(?:e?s?)?|include[ds]?|exclude[ds]?|rule[ds]? out",
    r"inclus(?:e?s?)?|exclu(?:e?s?)?|ecart(?:e|es|ee|ees)|admis(?:e)?|include[ds]|exclude[ds]|ruled out"
    r"|[,;]\s*(?:mais\s+)?pas\s+\w+|[,;]\s*(?:but\s+)?not\s+\w+|but not"
    r"|[,;][^.!?\n]{0,48}(?:ne |n['’])[^.!?\n]{0,35}\bpas"
    r"|[,;][^.!?\n]{0,48}\b(?:is|are|does|will|was)(?: not|n['’]t)"
    r"|[,;]\s*(?:only|seul(?:e?s?)?)\s+\w+|limited to|limite(?:e)? aux?",
)
# A date or time in a meeting record does not establish a count or duration.
_CALENDAR_VALUE = re.compile(
    r"\b\d{1,4}[-/:]\d{1,2}(?:[-/:]\d{1,4})?\b"
    r"|\b\d{1,2}\s+(?:janvier|fevrier|mars|avril|mai|juin|juillet|aout|septembre|octobre|novembre|decembre"
    r"|january|february|march|april|may|june|july|august|september|october|november|december)\b"
    r"|\b(?:a|at)\s+\d{1,2}\s*(?:h(?:\d{2})?|am|pm)\b",
)
_PAIRED_MEASURES = re.compile(r"\b(?:quantite ou (?:la )?duree|quantity or duration)\b")
_PAIRED_SCOPE = re.compile(
    r"\b(?:inclus(?:e?s?)? (?:ou|et) (?:exclu(?:e?s?)?|ecarte(?:e?s?)?)"
    r"|include[ds]? (?:or|and) (?:exclude[ds]?|rule[ds]? out))\b"
)
_COUNTED_NOUN = re.compile(r"\b(?:combien de|how many)\s+([^\W\d_]+)")
_FACT_DETAILS = (_QUANTITY, _DURATION, _SCOPE)
_TOPIC = re.compile(r"\b(?:concernant|pour|regarding|about|for)\s+([^\n,;:!?.]{1,120})(?=[\n,;:!?.]|$)")
_DETAILS = (
    _ACCESS_CODE,
    _detail(r"lieu|point de (?:rencontre|rendez-vous)|ou (?:se retrouve|nous retrouvons)|se retrouve ou"
            r"|(?:agreed|meeting) location|meeting (?:point|place)|where (?:are|shall|should|do) we meet(?:ing)?",
            r"lieu|rencontre|rendez-vous|salle|pavillon|adresse|meeting (?:place|point)|location|venue|address|room"),
    _DURATION, _QUANTITY, _SCOPE,
    _PROCEDURE, _REQUIREMENT,
    _detail(r"decision|decide|decided|choix valide|approved choice",
            r"decisions?|decid(?:e|ed)|choix|retenu|agreed to|opted for|chose|chosen"),
    _detail(r"(?:format|presenter|rediger)\b.{0,32}\b(?:message|retour|feedback)"
            r"|(?:message|retour|feedback)\b.{0,64}\bformat|communication (?:style|preferences?)",
            r"prefer(?:e|ence|ences|s|red)?|format|resume bref|brief summary"),
)
_IDENTITY = re.compile(
    r"^(?i:(?:qui est|connais[- ]tu|tu connais|who is|do you know)\s+)"
    r"(?P<name>[^\W\d_]+(?:[- ][^\W\d_]+){1,3}?)"
    r"(?i:(?:\s+(?:dans (?:notre|le) groupe|in (?:our|the) group))?)\s*[?!.]*$"
)
_RAW_SEARCH = re.compile(r'["«»“”]|\bOR\b|(?:^|\s)-|://')
_EXCLUSION = re.compile(r"\b(?:except|without|sans|not|pas|plutot|instead)\b")
_COMPOUND = re.compile(r"\b(?:et|and|ou|or|mais|but)\b|;|[?!.]\s+\w")


@dataclass(frozen=True, slots=True)
class QuestionEvidence:
    details: tuple[Detail, ...]
    names: tuple[tuple[str, ...], ...]
    subject: frozenset[str]
    identity_lookup: bool
    single_detail: bool
    topic: frozenset[str] = frozenset()
    counted_noun: str | None = None
    attribute: IdentityAttribute | None = None
    source_language: SourceLanguage | None = None
    storage: StorageLookup | None = None

    def answer_passage(self, title: str, excerpt: str, *, declared_language: object = None) -> str:
        if self.source_language is not None:
            return self.source_language.passage(title, excerpt, declared=declared_language, require_storage=True)
        return self.storage.passage(title, excerpt) if self.storage is not None else ""

    @property
    def topic_prefix_query(self) -> str:
        """Bounded PostgreSQL lexemes for acquiring passages to verify."""
        if self.source_language is not None:
            return self.source_language.prefix_query
        minimum = 2
        if (self.storage is not None or self.attribute is not None and self.attribute.kind == "contact") and any(
            len(t) >= 5 for t in self.topic
        ):
            minimum = 1
        if not self.single_detail or not minimum <= len(self.topic) <= 6:
            return ""
        if any(len(word) < 3 or not word.isalpha() for word in self.topic):
            return ""
        return " & ".join(f"{word}:*" for word in sorted(self.topic))

    @property
    def require_match(self) -> bool:
        return (self.identity_lookup or (self.single_detail and self.details == (_ACCESS_CODE,))
                or (self.attribute is not None and self.attribute.kind == "alias"))

    def same_subject(self, passage: str) -> bool:
        if self.topic:
            return self.topic.issubset(terms(passage))
        if self.names:
            return bool(matched_entities(passage, self.names))
        found = terms(passage)
        if self.require_match:
            # Lowercase place names often share their head noun (e.g. "maison").
            # A hard lookup needs the distinguishing words as well.
            return self.subject.issubset(found)
        return not self.subject or not self.subject.isdisjoint(found)

    def matching_facets(self, title: str, excerpt: str, *, declared_language: object = None) -> frozenset[int | str]:
        if self.source_language is not None or self.storage is not None:
            return frozenset({0}) if self.answer_passage(title, excerpt, declared_language=declared_language) else frozenset()
        if self.attribute is not None:
            # Distinct names represent separate possible answers to a first-name
            # lookup. Translations or repeated notes about one person cover it once.
            return self.attribute.matching_subjects(title, excerpt)
        passage = title + "\n" + excerpt
        if not self.same_subject(passage):
            return frozenset()
        if self.identity_lookup:
            return frozenset({0})
        folded = fold(passage)
        matches: set[int] = set()
        for index, detail in enumerate(self.details):
            if detail not in _FACT_DETAILS:
                if detail.evidence.search(folded):
                    matches.add(index)
                continue
            # Attribute a value to the subject in its own sentence. A short
            # standalone subject heading can supply it for an unlabeled value.
            heading_is_subject = bool(self.topic and self.topic == frozenset(terms(title)))
            for sentence in re.split(r"[!?\n]+|\.(?:\s+|$)", folded):
                if not heading_is_subject and not self.same_subject(sentence):
                    continue
                if detail != _SCOPE:
                    sentence = _CALENDAR_VALUE.sub(" ", sentence)
                if any(not self.counted_noun or detail != _QUANTITY or self.counted_noun in terms(match[0])
                       for match in detail.evidence.finditer(sentence)):
                    matches.add(index)
                    break
        return frozenset(matches)

    def supports(self, title: str, excerpt: str) -> bool:
        return bool(self.matching_facets(title, excerpt))


def parse_question_evidence(query: str, *, dated: bool = False) -> QuestionEvidence | None:
    if not query or _RAW_SEARCH.search(query):
        return None
    if not dated and (source := source_language_query(query)):
        return QuestionEvidence((), source.names, source.topic, False, True, source_language=source, storage=source.storage)
    if not dated and (storage := storage_lookup(query, direct=True)):
        return QuestionEvidence((), (), storage.subject, False, True, topic=storage.subject, storage=storage)
    direct = _IDENTITY.fullmatch(query.strip())
    if direct and all(word[0].isupper() for word in direct["name"].replace("-", " ").split()):
        names = entity_groups(direct["name"].replace("-", " "))
        if len(names) == 1 and len(names[0]) >= 2:
            return QuestionEvidence((), names, frozenset(), True, True)
    text = fold(query)
    available = (_DISCUSSION,) if dated else _DETAILS
    details = tuple(detail for detail in available if detail.question.search(text))
    if _EXCLUSION.search(text):
        return None
    if not details:
        attribute = None if dated else identity_attribute(query)
        if attribute is None:
            return None
        # A named project can be the only common term between the request and
        # an indexed passage in another language. Added candidates still need a
        # supported assignment before the document index can emit them.
        named_topic = frozenset[str]()
        if attribute.kind == "contact" and any(set(attribute.name) <= set(group) for group in entity_groups(query, limit=5)):
            named_topic = frozenset(attribute.name)
        return QuestionEvidence((), (attribute.name,), frozenset(), False, True, topic=named_topic, attribute=attribute)
    remainder = text
    if details == (_ACCESS_CODE,):
        before, after = _ACCESS_CODE.question.split(text, maxsplit=1)
        remainder = after if after.strip(" ?.!,") else before
    else:
        for detail in details:
            remainder = detail.question.sub(" ", remainder)
    subject = frozenset(terms(resource_query_terms(remainder)))
    names = tuple(group for group in entity_groups(query.replace("-", " "))
                  if len(group) > 1 or not subject.isdisjoint(group))
    # Remove only coordination internal to one requested fact. Keep accents
    # elsewhere so the French interrogative "où" is not mistaken for "ou".
    conjunctions = _PAIRED_MEASURES.sub("", text) if _PAIRED_MEASURES.search(text) else query.casefold()
    if _SCOPE in details and _PAIRED_SCOPE.search(text):
        conjunctions = _PAIRED_SCOPE.sub("", text)
    one_measure = set(details) == {_QUANTITY, _DURATION} and bool(_PAIRED_MEASURES.search(text))
    single = (len(details) == 1 or one_measure) and len(names) <= 1 and not _COMPOUND.search(conjunctions)
    topic = frozenset[str]()
    if any(d in _FACT_DETAILS for d in details) and (topic_match := _TOPIC.search(text)):
        topic = frozenset(terms(topic_match[1]))
    counted_noun = None
    if _QUANTITY in details and (unit := _COUNTED_NOUN.search(text)):
        counted_noun = next(iter(terms(unit[1])), None)
    if _PROCEDURE in details and _REQUIREMENT not in details:
        details = (*details, _REQUIREMENT)
    return QuestionEvidence(details, names, subject, False, single, topic, counted_noun)
