"""JSON-aware evidence locators shared by lexical and vector discovery."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, cast
import unicodedata

from .service import parse_json


@dataclass(frozen=True)
class DatasetPassage:
    json_pointer: str
    text: str


def terms(text: str) -> set[str]:
    normalized = "".join(char for char in unicodedata.normalize("NFKD", text.casefold())
                         if not unicodedata.combining(char))
    return set(re.findall(r"[^\W_]+", normalized))


def json_passages(content: str) -> list[DatasetPassage]:
    passages: list[DatasetPassage] = []

    def emit(value: Any, pointer: str) -> None:
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        for start in range(0, len(text), 1680):
            passages.append(DatasetPassage(pointer, text[start:start + 1800]))
            if start + 1800 >= len(text):
                break

    def walk(value: Any, pointer: str) -> None:
        if isinstance(value, list) and value:
            for index, child in enumerate(cast(list[Any], value)):
                walk(child, f"{pointer}/{index}")
        elif isinstance(value, dict) and any(isinstance(child, list) for child in cast(dict[str, Any], value).values()):
            mapping = cast(dict[str, Any], value)
            metadata = {key: child for key, child in mapping.items() if not isinstance(child, list)}
            if metadata:
                emit(metadata, pointer)
            for key, child in mapping.items():
                if isinstance(child, list):
                    walk(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        elif isinstance(value, dict) and value and all(isinstance(child, dict) for child in cast(dict[str, Any], value).values()):
            for key, child in cast(dict[str, Any], value).items():
                walk(child, pointer + "/" + key.replace("~", "~0").replace("/", "~1"))
        else:
            emit(value, pointer)

    walk(parse_json(content), "")
    return passages


def lexical_passages(content: str, query: str, *, limit: int = 3) -> list[DatasetPassage]:
    wanted = terms(query)
    ranked = sorted(enumerate(json_passages(content)),
                    key=lambda entry: (-len(terms(entry[1].text) & wanted), entry[0]))
    return [passage for _, passage in ranked[:limit]]


def embedding_passages(content: str) -> list[DatasetPassage]:
    """Pack large row collections without dropping their tail or row locators."""
    passages = json_passages(content)
    if len(passages) <= 512:
        return passages
    packed: list[DatasetPassage] = []
    group: list[DatasetPassage] = []
    size = 0

    def flush() -> None:
        if not group:
            return
        if len(group) == 1:
            packed.append(group[0])
            return
        parts = group[0].json_pointer.split("/")
        for passage in group[1:]:
            other = passage.json_pointer.split("/")
            common = 0
            for left, right in zip(parts, other):
                if left != right:
                    break
                common += 1
            parts = parts[:common]
        packed.append(DatasetPassage("/".join(parts),
            "\n".join(f"{p.json_pointer}: {p.text}" for p in group)))

    for passage in passages:
        length = len(passage.text) + len(passage.json_pointer) + 3
        if group and size + length > 1800:
            flush()
            group, size = [], 0
        group.append(passage)
        size += length
    flush()
    return packed
