"""Progressive dependency contracts for TypeScript and Vue frontend modules."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TypedDict, cast

try:
    from .project_context import (
        frontend_dependencies,
        frontend_import_specifiers,
        frontend_module_key,
        production_frontend_files,
        relative,
        resolve_frontend_import,
        strongly_connected_components,
    )
except ImportError:  # Direct execution from back/scripts.
    from project_context import (
        frontend_dependencies,
        frontend_import_specifiers,
        frontend_module_key,
        production_frontend_files,
        relative,
        resolve_frontend_import,
        strongly_connected_components,
    )


FRONTEND_BASELINE_PATH = "front/architecture-baseline.json"
PUBLIC_FRONTEND_ENTRYPOINTS = frozenset(
    {"contracts", "facade", "index", "interface", "types"}
)


class FrontendPrivateImport(TypedDict):
    source: str
    target: str


class FrontendDependency(TypedDict):
    source: str
    target: str


class FrontendArchitectureBaseline(TypedDict):
    schema_version: int
    dependencies: list[FrontendDependency]
    private_imports: list[FrontendPrivateImport]
    strongly_connected_components: list[list[str]]


def _is_public_frontend_import(normalized: str) -> bool:
    parts = Path(normalized.removeprefix("@/")).parts
    if len(parts) <= 2:
        return True
    return Path(parts[2]).stem in PUBLIC_FRONTEND_ENTRYPOINTS


def private_frontend_imports(root: Path) -> list[FrontendPrivateImport]:
    violations: set[tuple[str, str]] = set()
    for path in production_frontend_files(root):
        source_module = frontend_module_key(path, root)
        for specifier in frontend_import_specifiers(
            path.read_text(encoding="utf-8")
        ):
            resolved = resolve_frontend_import(path, specifier, root)
            if resolved is None:
                continue
            target_module, normalized = resolved
            if (
                source_module != target_module
                and not _is_public_frontend_import(normalized)
            ):
                violations.add((relative(path, root), normalized))
    return [
        {"source": source, "target": target}
        for source, target in sorted(violations)
    ]


def build_frontend_architecture_baseline(
    root: Path,
) -> FrontendArchitectureBaseline:
    edges = frontend_dependencies(root)
    return {
        "schema_version": 1,
        "dependencies": [
            {"source": edge["source"], "target": edge["target"]}
            for edge in edges
        ],
        "private_imports": private_frontend_imports(root),
        "strongly_connected_components": strongly_connected_components(edges),
    }


def serialize_frontend_architecture_baseline(
    baseline: FrontendArchitectureBaseline,
) -> str:
    return json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def load_frontend_architecture_baseline(
    root: Path,
) -> FrontendArchitectureBaseline:
    path = root / FRONTEND_BASELINE_PATH
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load {FRONTEND_BASELINE_PATH}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"{FRONTEND_BASELINE_PATH}: expected an object")
    return cast(FrontendArchitectureBaseline, raw)


def check_frontend_architecture_contracts(root: Path) -> list[str]:
    try:
        baseline = load_frontend_architecture_baseline(root)
    except ValueError as exc:
        return [str(exc)]
    if baseline.get("schema_version") != 1:
        return [
            f"{FRONTEND_BASELINE_PATH}: unsupported schema_version "
            f"{baseline.get('schema_version')!r}"
        ]

    current = build_frontend_architecture_baseline(root)
    errors: list[str] = []

    current_dependencies = {
        (item["source"], item["target"]) for item in current["dependencies"]
    }
    accepted_dependencies = {
        (item["source"], item["target"]) for item in baseline["dependencies"]
    }
    for source, target in sorted(current_dependencies - accepted_dependencies):
        errors.append(f"new frontend module dependency: {source} -> {target}")
    for source, target in sorted(accepted_dependencies - current_dependencies):
        errors.append(
            f"{FRONTEND_BASELINE_PATH}: remove resolved dependency "
            f"{source} -> {target} from baseline"
        )

    current_private = {
        (item["source"], item["target"]) for item in current["private_imports"]
    }
    accepted_private = {
        (item["source"], item["target"])
        for item in baseline["private_imports"]
    }
    for source, target in sorted(current_private - accepted_private):
        errors.append(f"{source}: new private frontend import {target}")
    for source, target in sorted(accepted_private - current_private):
        errors.append(
            f"{FRONTEND_BASELINE_PATH}: remove resolved private import "
            f"{source} -> {target} from baseline"
        )

    accepted_components = [
        set(component) for component in baseline["strongly_connected_components"]
    ]
    for component in current["strongly_connected_components"]:
        members = set(component)
        if not any(members <= accepted for accepted in accepted_components):
            errors.append(
                "new or expanded frontend dependency cycle: "
                + ", ".join(component)
            )
    return sorted(set(errors))
