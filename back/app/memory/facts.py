"""Atomic agent facts: identity links and data values, never narrated evidence."""

from html import escape
import json
import re
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr, field_validator


class MemoryFactReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str = Field(min_length=1, max_length=1_024)


class AtomicMemoryFact(BaseModel):
    """One subject/predicate/value assertion; provenance and time live elsewhere."""

    model_config = ConfigDict(extra="forbid")
    subject_ref: str = Field(default="", max_length=1_024,
        description="Existing memory:// contact, document:// resource or own galaris://agent/ URI. Omit for the current contact or agent.")
    predicate: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$",
        description="One stable snake_case property, such as preferred_language or wants.")
    value: StrictStr | StrictBool | StrictInt | FiniteFloat | MemoryFactReference
    negated: bool = False
    unit: str | None = Field(default=None, max_length=32)

    @field_validator("predicate", mode="before")
    @classmethod
    def normalize_predicate(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        plain = "".join(char for char in unicodedata.normalize("NFKD", value.casefold())
                        if not unicodedata.combining(char))
        return re.sub(r"[\s-]+", "_", plain.strip())

    @field_validator("value")
    @classmethod
    def raw_value(cls, value: StrictStr | StrictBool | StrictInt | FiniteFloat | MemoryFactReference
                  ) -> StrictStr | StrictBool | StrictInt | FiniteFloat | MemoryFactReference:
        if isinstance(value, str):
            value = value.strip()
            if not value or len(value) > 500 or "\n" in value or re.search(r"<[^>]+>", value):
                raise ValueError("Use one short raw value; split compound facts and keep narration out of memory.")
        return value


def render_atomic_fact(fact: AtomicMemoryFact, *, subject_label: str) -> str:
    """A deterministic editorial view preserves the existing Memory readers."""
    subject = f'<a href="{escape(fact.subject_ref, quote=True)}">{escape(subject_label)}</a>'
    if isinstance(fact.value, MemoryFactReference):
        value = f'<a href="{escape(fact.value.ref, quote=True)}">{escape(fact.value.ref)}</a>'
    else:
        value = escape(fact.value if isinstance(fact.value, str) else json.dumps(fact.value, allow_nan=False))
    rows = [("subject", subject), ("predicate", escape(fact.predicate)), ("value", value)]
    if fact.negated:
        rows.append(("negated", "true"))
    if fact.unit:
        rows.append(("unit", escape(fact.unit)))
    return "<table><tbody>" + "".join(f"<tr><th>{key}</th><td>{value}</td></tr>" for key, value in rows) + "</tbody></table>"
