"""Declarative module dependency contracts and progressive architecture baseline."""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path
from typing import TypedDict, cast

try:
    from .project_context import (
        DependencyEdge,
        backend_modules,
        dependency_edges,
        is_domain_module,
        module_key,
        parse_python,
        production_python_files,
        relative,
        strongly_connected_components,
    )
except ImportError:  # Direct execution from back/scripts.
    from project_context import (
        DependencyEdge,
        backend_modules,
        dependency_edges,
        is_domain_module,
        module_key,
        parse_python,
        production_python_files,
        relative,
        strongly_connected_components,
    )


CONTRACTS_PATH = "back/architecture.toml"
BASELINE_PATH = "back/architecture-baseline.json"


class ModuleContract(TypedDict):
    allowed_dependencies: list[str]
    max_domain_fan_out: int


class ArchitecturePolicy(TypedDict):
    version: int
    public_suffixes: list[str]
    modules: dict[str, ModuleContract]


class PrivateImport(TypedDict):
    source: str
    target: str


class ArchitectureBaseline(TypedDict):
    schema_version: int
    private_imports: list[PrivateImport]
    strongly_connected_components: list[list[str]]


def _mapping(value: object, location: str) -> dict[object, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{location} must be a table/object")
    return cast(dict[object, object], value)


def _string_list(value: object, location: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{location} must be a list of strings")
    items = cast(list[object], value)
    if not all(isinstance(item, str) for item in items):
        raise ValueError(f"{location} must be a list of strings")
    return cast(list[str], items)


def _integer(value: object, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{location} must be an integer")
    return value


def load_architecture_policy(root: Path) -> ArchitecturePolicy:
    path = root / CONTRACTS_PATH
    try:
        raw = cast(object, tomllib.loads(path.read_text(encoding="utf-8")))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"cannot read {CONTRACTS_PATH}: {exc}") from exc
    document = _mapping(raw, CONTRACTS_PATH)
    version = _integer(document.get("version"), f"{CONTRACTS_PATH}: version")
    public_suffixes = _string_list(
        document.get("public_suffixes"), f"{CONTRACTS_PATH}: public_suffixes"
    )
    module_tables = _mapping(document.get("module"), f"{CONTRACTS_PATH}: module")
    modules: dict[str, ModuleContract] = {}
    for raw_name, raw_contract in module_tables.items():
        if not isinstance(raw_name, str):
            raise ValueError(f"{CONTRACTS_PATH}: module names must be strings")
        table = _mapping(raw_contract, f"{CONTRACTS_PATH}: module.{raw_name}")
        allowed = sorted(
            set(
                _string_list(
                    table.get("allowed_dependencies"),
                    f"{CONTRACTS_PATH}: module.{raw_name}.allowed_dependencies",
                )
            )
        )
        maximum = _integer(
            table.get("max_domain_fan_out"),
            f"{CONTRACTS_PATH}: module.{raw_name}.max_domain_fan_out",
        )
        if maximum < 0:
            raise ValueError(
                f"{CONTRACTS_PATH}: module.{raw_name}.max_domain_fan_out must be non-negative"
            )
        if maximum != len(allowed):
            raise ValueError(
                f"{CONTRACTS_PATH}: module.{raw_name}.max_domain_fan_out must match "
                "the number of allowed dependencies"
            )
        modules[raw_name] = {
            "allowed_dependencies": allowed,
            "max_domain_fan_out": maximum,
        }
    return {
        "version": version,
        "public_suffixes": sorted(set(public_suffixes)),
        "modules": modules,
    }


def _private_import_from_object(value: object, index: int) -> PrivateImport:
    item = _mapping(value, f"{BASELINE_PATH}: private_imports[{index}]")
    source = item.get("source")
    target = item.get("target")
    if not isinstance(source, str) or not isinstance(target, str):
        raise ValueError(
            f"{BASELINE_PATH}: private_imports[{index}] needs string source and target"
        )
    return {"source": source, "target": target}


def load_architecture_baseline(root: Path) -> ArchitectureBaseline:
    path = root / BASELINE_PATH
    try:
        raw = cast(object, json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {BASELINE_PATH}: {exc}") from exc
    document = _mapping(raw, BASELINE_PATH)
    version = _integer(document.get("schema_version"), f"{BASELINE_PATH}: schema_version")
    raw_imports = document.get("private_imports")
    if not isinstance(raw_imports, list):
        raise ValueError(f"{BASELINE_PATH}: private_imports must be a list")
    private_imports = [
        _private_import_from_object(value, index)
        for index, value in enumerate(cast(list[object], raw_imports))
    ]
    raw_components = document.get("strongly_connected_components")
    if not isinstance(raw_components, list):
        raise ValueError(f"{BASELINE_PATH}: strongly_connected_components must be a list")
    components = [
        sorted(
            set(
                _string_list(
                    value,
                    f"{BASELINE_PATH}: strongly_connected_components[{index}]",
                )
            )
        )
        for index, value in enumerate(cast(list[object], raw_components))
    ]
    return {
        "schema_version": version,
        "private_imports": sorted(
            private_imports, key=lambda item: (item["source"], item["target"])
        ),
        "strongly_connected_components": sorted(components),
    }


def _absolute_imports(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(node.module)
    return imports


def _target_module(imported: str) -> str | None:
    parts = imported.split(".")
    if len(parts) < 2 or parts[0] not in {"core", "app", "bridge"}:
        return None
    return ".".join(parts[:2])


def _is_public_import(imported: str, target: str, suffixes: list[str]) -> bool:
    return imported == target or imported in {f"{target}.{suffix}" for suffix in suffixes}


def private_cross_module_imports(
    root: Path, public_suffixes: list[str]
) -> list[PrivateImport]:
    violations: set[tuple[str, str]] = set()
    for path in production_python_files(root):
        source_module = module_key(path, root)
        for imported in _absolute_imports(parse_python(path)):
            target_module = _target_module(imported)
            if (
                target_module is None
                or target_module == source_module
                or _is_public_import(imported, target_module, public_suffixes)
            ):
                continue
            violations.add((relative(path, root), imported))
    return [
        {"source": source, "target": target}
        for source, target in sorted(violations)
    ]


def current_dependency_edges(root: Path) -> list[DependencyEdge]:
    files = production_python_files(root)
    trees = {path: parse_python(path) for path in files}
    return dependency_edges(root, trees)


def build_architecture_baseline(
    root: Path, policy: ArchitecturePolicy | None = None
) -> ArchitectureBaseline:
    effective_policy = policy or load_architecture_policy(root)
    edges = current_dependency_edges(root)
    return {
        "schema_version": 1,
        "private_imports": private_cross_module_imports(
            root, effective_policy["public_suffixes"]
        ),
        "strongly_connected_components": strongly_connected_components(edges),
    }


def serialize_architecture_baseline(baseline: ArchitectureBaseline) -> str:
    return json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def check_architecture_contracts(root: Path) -> list[str]:
    try:
        policy = load_architecture_policy(root)
        baseline = load_architecture_baseline(root)
    except ValueError as exc:
        return [str(exc)]

    errors: list[str] = []
    if policy["version"] != 1:
        errors.append(f"{CONTRACTS_PATH}: unsupported version {policy['version']}")
    if baseline["schema_version"] != 1:
        errors.append(
            f"{BASELINE_PATH}: unsupported schema_version {baseline['schema_version']}"
        )

    active_modules = {module["name"] for module in backend_modules(root)}
    contracted_modules = set(policy["modules"])
    for name in sorted(active_modules - contracted_modules):
        errors.append(f"{CONTRACTS_PATH}: active module {name} has no dependency contract")
    for name in sorted(contracted_modules - active_modules):
        errors.append(f"{CONTRACTS_PATH}: contract references inactive module {name}")

    edges = current_dependency_edges(root)
    outgoing: dict[str, set[str]] = {}
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if not is_domain_module(source) or not is_domain_module(target):
            continue
        outgoing.setdefault(source, set()).add(target)
        contract = policy["modules"].get(source)
        if contract is None:
            errors.append(f"{CONTRACTS_PATH}: {source} has no contract for dependency {target}")
        elif target not in contract["allowed_dependencies"]:
            errors.append(f"{source} -> {target}: dependency is not allowed by {CONTRACTS_PATH}")

    for module, contract in sorted(policy["modules"].items()):
        actual_dependencies = outgoing.get(module, set())
        actual_fan_out = len(actual_dependencies)
        if actual_fan_out > contract["max_domain_fan_out"]:
            errors.append(
                f"{module}: domain fan-out {actual_fan_out} exceeds budget "
                f"{contract['max_domain_fan_out']}"
            )
        for target in sorted(set(contract["allowed_dependencies"]) - actual_dependencies):
            errors.append(
                f"{CONTRACTS_PATH}: remove unused allowed dependency {module} -> {target}"
            )

    current_private = private_cross_module_imports(root, policy["public_suffixes"])
    current_private_set = {(item["source"], item["target"]) for item in current_private}
    baseline_private_set = {
        (item["source"], item["target"]) for item in baseline["private_imports"]
    }
    for source, target in sorted(current_private_set - baseline_private_set):
        errors.append(f"{source}: new private cross-module import {target}")
    for source, target in sorted(baseline_private_set - current_private_set):
        errors.append(
            f"{BASELINE_PATH}: remove resolved private import {source} -> {target} from baseline"
        )

    baseline_components = [set(component) for component in baseline["strongly_connected_components"]]
    for component in strongly_connected_components(edges):
        members = set(component)
        if not any(members <= accepted for accepted in baseline_components):
            errors.append(
                "new or expanded dependency cycle: " + ", ".join(component)
            )
    return sorted(set(errors))
