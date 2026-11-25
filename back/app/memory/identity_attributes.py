"""Subject attribution for named role and nickname lookups in conversation."""

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal

from .relevance import entity_groups, fold, matched_entities, terms


_ALIAS_WORD = r"(?:surnom|sobriquet|nom de code|nickname|code[ -]?name|alias)"
_DIRECT_ALIAS = re.compile(
    r"^(?:(?:quel|quelle|what|which)\s+(?:(?:est|etait|is|was)\s+)?"
    r"|(?:rappelle[- ]moi|donne[- ]moi|remind me of|tell me|give me)\s+)"
    r"(?:(?:le|son|the|their|his|her|private|ancien|old)\s+)*" + _ALIAS_WORD
    + r"(?:\s+(?:prive|utilise|used)){0,2}\s+(?:de\b|du\b|d['’]|of\b|for\b|pour\b)"
    r"|^what (?:is|was) [\w -]{1,90}['’]s (?:private )?" + _ALIAS_WORD + r"\s*[?.!]*$"
)
_ROLE_REQUEST = re.compile(
    r"\bde quoi s['’]occupe\b|\bwhat does .{1,60} (?:handle|do(?: for a living)?)\s*[?.!]*$"
    r"|\b(?:quel(?:le)?s?|what|which|rappell?er?(?:-moi)?|redonne|donne|remind me of|tell me|give me)\s+"
    r"(?:(?:est|sont|is|are|le|la|les|son|sa|ses|the|their|his|her|my|me|moi)\s+)*"
    r"(?:roles?|responsabilites?|responsibilities|job title|fonction|profession)\b"
    r"(?=\s*(?:[?.!]|$)|\s+(?:de\b|du\b|d['’]|of\b))"
    r"|\b(?:what (?:is|are)|remind me of|tell me) [\w -]{1,90}['’]s\s+(?:role|responsibilities|job title)\s*[?.!]*$"
)
_MULTIPLE = re.compile(r'\b(?:et|and|or|mais|but|sans|except|without|instead|comment|how|pourquoi|why)\b|[;"«»“”]|://')
_PROJECT = re.compile(r"\b(?:projet|project)\b")
_OLD_PROJECT = re.compile(r"\b(?:ancien|anciennement|old|former|previous)\s+(?:projet|project)\b")
_PROJECT_MODIFIERS = frozenset(terms("ancien ancienne nouveau nouvelle old former previous new project projet"))
_QUESTION_FILLER = frozenset(terms("role fonction profession nickname alias surnom nom code can give tell"))
_NAME_WORD = r"[A-ZÀ-ÖØ-Þ][^\W\d_]*"
_NAME = _NAME_WORD + r"(?:[ -]" + _NAME_WORD + r"){0,3}"
_NAME_PATTERN = re.compile(_NAME)
_QUOTED_NAME = re.compile(r'(?:«\s*(' + _NAME + r')\s*»|“(' + _NAME + r')”|"(' + _NAME + r')")')
_ALIAS_APPOSITION = re.compile(
    r"^(?P<subject>[^,]+),\s*(?:aka|also known as|nicknamed|surnomm[ée]e?|aussi appel[ée]e?)\s+\w+", re.I)
_ROLE = re.compile(
    r"\b(?P<actor>" + _NAME + r")\s+(?i:"
    r"dirige|coordonne|anime|pilote|supervise|g[èe]re|s['’]occupe de|travaille comme"
    r"|leads|manages|coordinates|supervises|runs|works as|serves as|is (?:responsible for|in charge of)"
    r"|(?:est (?:le |la |l['’]|un |une )|is (?:the |a |an ))[^\W\d_]+(?:[ '-][^\W\d_]+){0,5}?"
    r"\s+(?:pour|chez|for|at)|est\s+(?:responsable|charg[ée]e?|r[ée]f[ée]rente?|"
    r"[^\W\d_]+(?:atrice|ateur|iste|ienne|euse|trice)|architecte|comptable|ing[ée]nieure?)"
    r"|is an? [\w-]+(?:ist|ian|eer|tor|yer|er|or)(?=\s*$)"
    r")\b"
)
# Extract the person or project on the subject side. A nickname assigned to a
# person inside a project is evidence about that person, even in a project note.
_ALIAS_SUBJECTS = tuple(re.compile(pattern, re.IGNORECASE) for pattern in (
    r"\b" + _ALIAS_WORD + r"\b(?:\s+(?:prive|private|utilise|used)){0,2}\s+(?:de |d['’]|du |des |of |for |pour )"
    r"(?P<subject>.+?)(?:\s+(?:est|etait|is|was)\s+|\s*:\s*)\S+",
    r"^.+?\s+(?:est|is)\s+(?:le |un |the |a )?" + _ALIAS_WORD + r"\s+(?:de |d['’]|du |of |for )(?P<subject>.+)$",
    r"^(?P<subject>.+?)['’]s\s+(?:private\s+)?" + _ALIAS_WORD + r"\s+(?:is|was)\s+\S+",
    r"^.+?\s+is\s+(?P<subject>.+?)['’]s\s+" + _ALIAS_WORD + r"$",
    r"^(?P<subject>.+?)\s+(?:est surnomme[e]?|is nicknamed|goes by|is also known as|"
    r"a pour (?:surnom|nom de code)|porte le nom de code|is codenamed)\s+\S+",
))
_UNCERTAIN = re.compile(r'\b(?:si|if|maybe|perhaps|might|supposons|imaginons)\b|["«»“”]')
_ROLE_FIELD = re.compile(r"^(?:role|fonction|profession|job title)\s*[:=]\s*\w+")
_ALIAS_FIELD = re.compile(r"^" + _ALIAS_WORD + r"\s*[:=]\s*\w+")

_CONTACT_LABEL = r"(?:contact|point de contact|interlocut(?:eur|rice)|r[ée]f[ée]rente?|point of contact|contact person)"
_TOPIC_PHRASE = r"(?P<topic>[\w'’ -]{1,80})"
_CONTACT_REQUESTS = tuple(re.compile(pattern) for pattern in (
    r"(?:qui est (?:le|la|notre)|who is (?:the|our)) " + _CONTACT_LABEL
    + r" (?:pour|de|du|for|on) " + _TOPIC_PHRASE,
    r"(?:who (?:should|can|do) (?:i|we) (?:contact|speak (?:to|with)|talk to)|"
    r"[aà] qui (?:dois-je|peut-on|puis-je) (?:parler|m['’]adresser)) (?:about|for|pour|de) " + _TOPIC_PHRASE,
    _TOPIC_PHRASE + r",\s*(?:je dois en parler [aà] qui|[aà] qui (?:dois-je|puis-je) m['’]adresser)",
))
_CONTACT_ACTOR = r"(?P<actor>" + _NAME + r")"
_CONTACT_ASSIGNMENTS = tuple(re.compile(pattern) for pattern in (
    _CONTACT_ACTOR + r"\s+(?i:(?:est|is|serves as) (?:le|la|notre|the|our) " + _CONTACT_LABEL
    + r" (?:de|du|pour|for|on))\s+" + _TOPIC_PHRASE,
    r"(?i:(?:pour|for) )" + _TOPIC_PHRASE + r",\s*(?i:(?:le |la |the |our |notre )?" + _CONTACT_LABEL
    + r"\s*(?:est |is |: ?))" + _CONTACT_ACTOR,
    r"(?i:(?:le |la |the |our |notre )?" + _CONTACT_LABEL + r" (?:de|du|pour|for|on) )"
    + _TOPIC_PHRASE + r"\s*(?i:\s+est\s+|\s+is\s+|:\s*)" + _CONTACT_ACTOR,
    r"(?i:(?:pour|for) )" + _TOPIC_PHRASE
    + r",\s*(?i:(?:contact(?:ez|er)?|adressez-vous [àa]|reach out to|speak to) )" + _CONTACT_ACTOR,
))
_CONTACT_FIELD = re.compile(r"(?i:" + _CONTACT_LABEL + r")\s*[:=]\s*" + _CONTACT_ACTOR)
_MISSING_CONTACT = frozenset(("unknown", "unassigned", "none", "nobody", "tbd", "inconnu", "inconnue", "personne", "a definir"))


def _contact_topic(value: str) -> str:
    text = fold(value).strip()
    text = re.sub(r"^(?:(?:le|la|the) )?(?:projet|project)\s+", "", text)
    return re.sub(r"\s+project$", "", text).strip()


@dataclass(frozen=True, slots=True)
class IdentityAttribute:
    kind: Literal["role", "alias", "contact"]
    name: tuple[str, ...]
    project: bool
    old_project: bool

    def matches_owner(self, owner: str) -> bool:
        words = terms(owner)
        folded = fold(owner)
        if _PROJECT.search(folded):
            return ((not self.old_project or bool(_OLD_PROJECT.search(folded)))
                    and bool(matched_entities(owner, (self.name,)))
                    and set(words).difference(self.name) <= _PROJECT_MODIFIERS)
        if self.project:
            return False
        return words == self.name or (_NAME_PATTERN.fullmatch(owner) is not None
                                      and bool(matched_entities(owner, (self.name,))))

    def matching_subjects(self, title: str, excerpt: str) -> frozenset[str]:
        # The native title is a truncated copy of the body. Inspect complete
        # assertions first so a truncated question cannot become a statement.
        subjects: set[str] = set()
        if self.kind == "contact":
            for sentence in re.findall(r"[^.!?;\n]+[.!?]?", excerpt or title):
                clause = sentence.strip().rstrip(".!")
                if clause.endswith("?") or _UNCERTAIN.search(fold(clause)):
                    continue
                if field_match := _CONTACT_FIELD.fullmatch(clause):
                    if terms(_contact_topic(title)) == self.name:
                        subjects.add(fold(field_match["actor"]))
                for pattern in _CONTACT_ASSIGNMENTS:
                    # A comma may introduce a description after the project name.
                    match = pattern.fullmatch(clause) or pattern.fullmatch(clause.partition(",")[0])
                    if match and terms(_contact_topic(match["topic"])) == self.name:
                        subjects.add(fold(match["actor"]))
            return frozenset(subjects.difference(_MISSING_CONTACT))
        field = _ROLE_FIELD if self.kind == "role" else _ALIAS_FIELD
        for sentence in re.findall(r"[^.!?;\n]+[.!?]?", excerpt or title):
            if self.kind == "alias":
                sentence = _QUOTED_NAME.sub(lambda m: next(value for value in m.groups() if value), sentence)
            if sentence.endswith("?") or _UNCERTAIN.search(fold(sentence)):
                continue
            if field.match(fold(sentence.strip())) and self.matches_owner(title):
                subjects.add(fold(title.strip()))
            if self.kind == "alias" and (alias := _ALIAS_APPOSITION.match(sentence.strip())):
                if self.matches_owner(alias["subject"]):
                    subjects.add(fold(alias["subject"]))
            for clause in sentence.rstrip(".!").split(","):
                if self.kind == "role":
                    subjects.update(fold(match["actor"]) for match in _ROLE.finditer(clause)
                                    if matched_entities(match["actor"], (self.name,)))
                    continue
                # Retain capitals to distinguish a proper name from a sentence
                # such as "Alice says Bob" on the subject side of "goes by".
                clause = "".join(c for c in unicodedata.normalize("NFKD", clause.strip())
                                 if not unicodedata.combining(c))
                for pattern in _ALIAS_SUBJECTS:
                    if match := pattern.search(clause):
                        owner = match["subject"].strip()
                        if self.matches_owner(owner):
                            subjects.add(fold(owner))
        return frozenset(subjects)


def identity_attribute(query: str) -> IdentityAttribute | None:
    text = fold(query)
    if not _MULTIPLE.search(text) and not re.search(r"\bou\b", query.casefold()):
        for pattern in _CONTACT_REQUESTS:
            if match := pattern.fullmatch(text.strip().rstrip("?!. ")):
                topic = terms(_contact_topic(match["topic"]))
                if topic and len(topic) <= 6:
                    return IdentityAttribute("contact", topic, True, False)
    role, alias = bool(_ROLE_REQUEST.search(text)), bool(_DIRECT_ALIAS.search(text.strip()))
    if role == alias or _MULTIPLE.search(text) or text.count("?") > 1:
        return None
    if re.search(r"\bou\b", query.casefold()):
        return None
    if alias and re.search(r"[?!.]\s+\w", text):
        return None
    groups = entity_groups(query, limit=5)
    names = tuple(group for group in groups if not _QUESTION_FILLER.issuperset(group))
    if len(names) != 1:
        return None
    return IdentityAttribute("role" if role else "alias", names[0],
                             bool(_PROJECT.search(text)), bool(_OLD_PROJECT.search(text)))
