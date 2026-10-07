"""Strict JSON boundaries for the portable benchmark format."""

from __future__ import annotations

import hashlib
import json
from dataclasses import fields
from pathlib import Path
from typing import cast

from .generate import Answer, Corpus, Group, Memory, Query, VERSION


def record(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object with string keys")
    typed = cast(dict[object, object], value)
    if any(not isinstance(k, str) for k in typed):
        raise ValueError("Expected a JSON object with string keys")
    return cast(dict[str, object], value)


def sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ValueError("Expected a JSON array")
    return cast(list[object], value)


def string(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("Expected a JSON string")
    return value


def strings(value: object) -> tuple[str, ...]:
    return tuple(string(item) for item in sequence(value))


def nullable(value: object) -> str | None:
    return None if value is None else string(value)


def string_map(value: object) -> dict[str, str]:
    return {key: string(item) for key, item in record(value).items()}


def json_records(path: Path) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                result.append(record(json.loads(line)))
            except (ValueError, TypeError) as error:
                raise ValueError(f"{path.name}:{line_number}: invalid record: {error}") from error
    return result


def _keys(data: dict[str, object], expected: set[str]) -> None:
    if set(data) != expected:
        raise ValueError(f"Schema mismatch: missing={sorted(expected-set(data))}, extra={sorted(set(data)-expected)}")


def _anchor(value: object) -> dict[str, str | int] | None:
    if value is None:
        return None
    result: dict[str, str | int] = {}
    for key, item in record(value).items():
        if isinstance(item, bool) or not isinstance(item, (str, int)):
            raise ValueError("Invalid calendar anchor")
        result[key] = item
    return result


def load(directory: Path) -> Corpus:
    manifest = record(json.loads((directory / "manifest.json").read_text(encoding="utf-8")))
    if manifest.get("version") != VERSION or manifest.get("synthetic") is not True:
        raise ValueError("Unsupported or non-synthetic corpus")
    hashes = string_map(manifest["sha256"])
    expected_files = {"memories.jsonl", "queries.jsonl", "answers.jsonl"}
    if set(hashes) != expected_files:
        raise ValueError("Invalid manifest file list")
    for filename in sorted(expected_files):
        if hashlib.sha256((directory / filename).read_bytes()).hexdigest() != hashes[filename]:
            raise ValueError(f"Checksum mismatch: {filename}")

    memories: list[Memory] = []
    for d in json_records(directory / "memories.jsonl"):
        _keys(d, {field.name for field in fields(Memory)})
        memories.append(Memory(
            string(d["id"]), string(d["world_id"]), string(d["language"]), string(d["title"]),
            string(d["content_html"]), strings(d["allowed_actor_ids"]),
            nullable(d["contact_scope"]), string(d["state"]), string(d["known_at"]), string(d["recorded_at"]),
            nullable(d["event_start"]), nullable(d["event_end"]), nullable(d["valid_from"]),
            nullable(d["valid_until"]), _anchor(d["temporal_anchor"]), string_map(d["source"])))
    queries: list[Query] = []
    for d in json_records(directory / "queries.jsonl"):
        _keys(d, {field.name for field in fields(Query)})
        queries.append(Query(
            string(d["id"]), string(d["world_id"]), string(d["profile"]), string(d["domain"]),
            string(d["family"]), string(d["split"]), string(d["language"]), string(d["surface"]),
            string(d["actor_id"]), string(d["contact_id"]), string(d["timestamp"]), string(d["timezone"]),
            tuple(string_map(item) for item in sequence(d["history"])), string(d["message"])))
    answers: list[Answer] = []
    for d in json_records(directory / "answers.jsonl"):
        _keys(d, {field.name for field in fields(Answer)})
        groups: list[Group] = []
        for item in sequence(d["required"]):
            group = record(item)
            _keys(group, {field.name for field in fields(Group)})
            groups.append(Group(string(group["facet"]), strings(group["any_of"]), string(group["assertion"])))
        answers.append(Answer(string(d["query_id"]), tuple(groups), strings(d["optional_ids"]),
                              string_map(d["forbidden"]), string(d["response_mode"]),
                              nullable(d["temporal_start"]), nullable(d["temporal_end"]), string(d["rationale"])))
    if manifest["memory_count"] != len(memories) or manifest["query_count"] != len(queries):
        raise ValueError("Manifest counts disagree with corpus")
    return Corpus(tuple(memories), tuple(queries), tuple(answers))
