"""Rename persisted format constraints without rewriting user data or BPMN layout."""

from copy import deepcopy
import json
import re
from typing import cast
from xml.parsers.expat import ParserCreate
from xml.sax.saxutils import escape

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from core.dbadmin import DbAdminAction, DbAdminPhase, DbAdminRegistry, SchemaTransitionSet

_WORKFLOW = "https://galaris.ai/bpmn/v1}workflow"
_OPENING_TAG = re.compile(rb'''<(?:[^>"']|"[^"]*"|'[^']*')*>''')


def rename_graph(value: object) -> object:
    if not isinstance(value, dict):
        return value
    graph = deepcopy(cast(dict[str, object], value))
    variables = graph.get("variables")
    if isinstance(variables, list):
        for raw in cast(list[object], variables):
            if not isinstance(raw, dict):
                continue
            variable = cast(dict[str, object], raw)
            if "document_type" not in variable:
                continue
            old = variable.pop("document_type")
            if "document_format" in variable and variable["document_format"] != old:
                raise ValueError("Conflicting persisted document format constraints")
            variable["document_format"] = old
    nodes = graph.get("nodes")
    if isinstance(nodes, list):
        for raw in cast(list[object], nodes):
            if isinstance(raw, dict):
                node = cast(dict[str, object], raw)
                if "body" in node:
                    node["body"] = rename_graph(node["body"])
    return graph


def rename_bpmn(source: str) -> str:
    if "document_type" not in source:
        return source
    raw = source.encode("utf-8")
    parser = ParserCreate(encoding="utf-8", namespace_separator="}")
    changes: list[tuple[int, int, bytes]] = []
    active: tuple[int, list[str]] | None = None

    def start(name: str, _attributes: dict[str, str]) -> None:
        nonlocal active
        if name == _WORKFLOW:
            opening = _OPENING_TAG.match(raw, parser.CurrentByteIndex)
            if opening is None:
                raise ValueError("Invalid persisted workflow extension")
            active = opening.end(), []

    def characters(content: str) -> None:
        if active is not None:
            active[1].append(content)

    def end(name: str) -> None:
        nonlocal active
        if name == _WORKFLOW and active is not None:
            content = "".join(active[1])
            if "document_type" in content:
                original: object = json.loads(content)
                migrated = rename_graph(original)
                if original != migrated:
                    replacement = escape(json.dumps(migrated, ensure_ascii=False)).encode("utf-8")
                    changes.append((active[0], parser.CurrentByteIndex, replacement))
            active = None

    def reject_doctype(*_arguments: object) -> None:
        raise ValueError("DOCTYPE is forbidden in persisted BPMN")

    parser.StartElementHandler = start
    parser.CharacterDataHandler = characters
    parser.EndElementHandler = end
    parser.StartDoctypeDeclHandler = reject_doctype
    parser.Parse(raw, True)
    for begin, finish, replacement in reversed(changes):
        raw = raw[:begin] + replacement + raw[finish:]
    return raw.decode("utf-8")


def rename_snapshot(value: dict[str, object]) -> dict[str, object]:
    snapshot = deepcopy(value)
    raw = snapshot.get("definition")
    if isinstance(raw, dict):
        definition = cast(dict[str, object], raw)
        if "graph" in definition:
            definition["graph"] = rename_graph(definition["graph"])
        if isinstance(definition.get("xml"), str):
            definition["xml"] = rename_bpmn(cast(str, definition["xml"]))
    return snapshot


async def _migrate(session: AsyncSession, *, write: bool) -> bool:
    # All identifiers are closed migration-owned table/column names.
    for table, column in (("process_definitions", "bpmn_xml"),
                          ("process_definition_revisions", "bpmn_xml"), ("process_runs", "launch_snapshot")):
        cursor = ""
        while True:
            # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
            rows = (await session.execute(text(f"""SELECT id,{column} FROM {table}
                WHERE id::text>:cursor AND {column}::text LIKE '%document_type%'
                ORDER BY id::text LIMIT 100"""), {"cursor": cursor})).mappings().all()
            if not rows:
                break
            for row in rows:
                original = row[column]
                migrated = rename_snapshot(cast(dict[str, object], original)) if column == "launch_snapshot" else rename_bpmn(str(original))
                if migrated != original:
                    if not write:
                        return False
                    expression = "CAST(:value AS jsonb)" if column == "launch_snapshot" else ":value"
                    # nosemgrep: python.sqlalchemy.security.audit.avoid-sqlalchemy-text.avoid-sqlalchemy-text
                    await session.execute(text(f"UPDATE {table} SET {column}={expression} WHERE id=:id"),
                        {"id": row["id"], "value": json.dumps(migrated) if column == "launch_snapshot" else migrated})
            cursor = str(rows[-1]["id"])
    return True


async def transfer(session: AsyncSession, _delta: SchemaTransitionSet) -> None:
    await _migrate(session, write=True)


async def complete(session: AsyncSession, _delta: SchemaTransitionSet) -> bool:
    return await _migrate(session, write=False)


def register(registry: DbAdminRegistry) -> None:
    registry.register_action(DbAdminAction(key="app.process.document_format_constraints", phase=DbAdminPhase.AFTER_DATASET,
        checksum="rename-only-document-format-constraints-v1",
        predicate=lambda delta: "documents.document_type" in delta.removed_columns or delta.table_added("documents"),
        handler=transfer, postcondition=complete,
        requires_schema=frozenset({"process_definitions.bpmn_xml", "process_definition_revisions.bpmn_xml", "process_runs.launch_snapshot"})))
