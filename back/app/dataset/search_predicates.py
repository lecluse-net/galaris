"""Shared text discovery for the human library and agent resource provider."""

from sqlalchemy import Text, cast, func, or_
from sqlalchemy.sql.elements import ColumnElement

from .models import Dataset


def search_vector() -> ColumnElement[str]:
    return func.to_tsvector("simple", func.concat_ws(" ", Dataset.title,
        func.coalesce(Dataset.summary_content, ""), cast(Dataset.keywords, Text), Dataset.content))


def text_search_clause(query: str) -> ColumnElement[bool]:
    return or_(search_vector().op("@@")(func.websearch_to_tsquery("simple", query)),
        Dataset.title.icontains(query, autoescape=True), Dataset.content.icontains(query, autoescape=True))
