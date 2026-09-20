"""Generate a deterministic, code-derived map of the Galaris project.

The generator deliberately relies on the standard library and static analysis. It must not
import application modules: imports can require settings, a database, or external services.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Literal, TypedDict, cast


Layer = Literal["core", "app", "bridge"]
HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head", "websocket"})
BACKEND_CAPABILITY_FILES = (
    "contracts.py",
    "facade.py",
    "interface.py",
    "models.py",
    "schemas.py",
    "router.py",
    "mcp.py",
    "privileges.py",
    "listener.py",
)
FRONTEND_CAPABILITIES = (
    "pages",
    "components",
    "services",
    "stores",
    "navigation.ts",
    "i18n.ts",
    "presentation.ts",
)


class BackendModule(TypedDict):
    name: str
    layer: Layer
    conditional: bool
    path: str
    exists: bool
    capabilities: list[str]


class FrontendPage(TypedDict):
    module: str
    file: str
    route_hint: str


class FrontendModule(TypedDict):
    name: str
    layer: Literal["core", "app", "bridge"]
    path: str
    exists: bool
    capabilities: list[str]
    pages: list[FrontendPage]


class DependencyEdge(TypedDict):
    source: str
    target: str
    files: list[str]


class ModuleDependencyDegree(TypedDict):
    module: str
    count: int
    modules: list[str]


class DependencyMetrics(TypedDict):
    domain_edges: int
    direct_cycles: list[list[str]]
    strongly_connected_components: list[list[str]]
    fan_in: list[ModuleDependencyDegree]
    fan_out: list[ModuleDependencyDegree]


class RouteInfo(TypedDict):
    module: str
    method: str
    declared_path: str
    handler: str
    authorized: bool
    file: str
    line: int


class ModelInfo(TypedDict):
    module: str
    class_name: str
    table: str
    history_mixin: bool
    foreign_keys: list[str]
    file: str
    line: int


class McpToolInfo(TypedDict):
    module: str
    namespace: str
    name: str
    handler: str
    file: str
    line: int


class PrivilegeInfo(TypedDict):
    module: str
    constant: str
    value: str
    file: str
    line: int


class SettingsMap(TypedDict):
    declared: list[str]
    env_example: list[str]
    missing_from_env_example: list[str]
    env_only: list[str]


class BackendMap(TypedDict):
    modules: list[BackendModule]
    dependencies: list[DependencyEdge]
    dependency_metrics: DependencyMetrics
    routes: list[RouteInfo]
    models: list[ModelInfo]
    mcp_tools: list[McpToolInfo]
    privileges: list[PrivilegeInfo]


class FrontendMap(TypedDict):
    modules: list[FrontendModule]
    dependencies: list[DependencyEdge]
    dependency_metrics: DependencyMetrics
    pages: list[FrontendPage]


class ProjectMap(TypedDict):
    schema_version: int
    generated_by: str
    backend: BackendMap
    frontend: FrontendMap
    settings: SettingsMap


def relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def contains_source(path: Path, suffixes: frozenset[str]) -> bool:
    """Ignore empty directories and bytecode absent from a source snapshot."""
    return any(item.is_file() and item.suffix in suffixes for item in path.rglob("*"))


def parse_python(path: Path) -> ast.Module:
    try:
        return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise ValueError(f"Cannot map invalid Python file {path}: {exc}") from exc


def production_python_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for layer in ("core", "app", "bridge"):
        layer_root = root / "back" / layer
        if not layer_root.exists():
            continue
        for path in layer_root.rglob("*.py"):
            parts = path.relative_to(layer_root).parts
            if "tests" in parts or "__pycache__" in parts:
                continue
            files.append(path)
    return sorted(files)


def module_key(path: Path, root: Path) -> str:
    parts = list(path.relative_to(root / "back").parts)
    if not parts:
        raise ValueError(f"Cannot derive a backend module from {path}")
    if len(parts) < 2:
        return Path(parts[0]).stem
    second = Path(parts[1]).stem
    return f"{parts[0]}.{second}"


def _assigned_expressions(tree: ast.Module) -> dict[str, ast.expr]:
    assignments: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments[target.id] = node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.value is not None
        ):
            assignments[node.target.id] = node.value
    return assignments


def _module_literals(
    node: ast.AST,
    assignments: dict[str, ast.expr],
    conditional: bool = False,
    resolving: frozenset[str] = frozenset(),
) -> list[tuple[str, bool]]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        value = node.value
        if re.fullmatch(r"(?:core|app|bridge)\.[a-zA-Z0-9_]+", value):
            return [(value, conditional)]
        return []
    if isinstance(node, ast.Name) and node.id in assignments and node.id not in resolving:
        return _module_literals(
            assignments[node.id],
            assignments,
            conditional=conditional,
            resolving=resolving | {node.id},
        )
    if isinstance(node, ast.Starred):
        return _module_literals(
            node.value,
            assignments,
            conditional=True,
            resolving=resolving,
        )
    values: list[tuple[str, bool]] = []
    for child in ast.iter_child_nodes(node):
        values.extend(
            _module_literals(
                child,
                assignments,
                conditional=conditional,
                resolving=resolving,
            )
        )
    return values


def backend_modules(root: Path) -> list[BackendModule]:
    modules_file = root / "back" / "modules.py"
    tree = parse_python(modules_file)
    assignments = _assigned_expressions(tree)
    entries: list[tuple[str, bool]] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "MODULES" for target in targets):
            continue
        value = node.value
        if value is not None:
            entries.extend(_module_literals(value, assignments))

    result: list[BackendModule] = []
    seen: set[str] = set()
    for name, conditional in entries:
        if name in seen:
            continue
        seen.add(name)
        layer = cast(Layer, name.split(".", 1)[0])
        path = root / "back" / Path(*name.split("."))
        capabilities = [item for item in BACKEND_CAPABILITY_FILES if (path / item).is_file()]
        if contains_source(path / "i18n", frozenset({".py"})):
            capabilities.append("i18n/")
        if contains_source(path / "tests", frozenset({".py"})):
            capabilities.append("tests/")
        result.append(
            {
                "name": name,
                "layer": layer,
                "conditional": conditional,
                "path": relative(path, root),
                "exists": path.is_dir(),
                "capabilities": sorted(capabilities),
            }
        )
    return result


def frontend_module_names(root: Path) -> list[str]:
    content = (root / "front" / "modules.ts").read_text(encoding="utf-8")
    names = re.findall(r"['\"]((?:core|app|bridge)/[a-zA-Z0-9_]+)['\"]", content)
    return list(dict.fromkeys(names))


def page_route_hint(module_name: str, page: Path, pages_root: Path) -> str:
    relative_page = page.relative_to(pages_root).with_suffix("")
    segments = list(relative_page.parts)
    if segments and segments[-1] == "index":
        segments.pop()

    route_segments: list[str] = [module_name.rsplit("/", 1)[-1]]
    for segment in segments:
        catch_all = re.fullmatch(r"\[\.\.\.([a-zA-Z0-9_]+)\]", segment)
        dynamic = re.fullmatch(r"\[([a-zA-Z0-9_]+)\]", segment)
        if catch_all:
            route_segments.append(f":{catch_all.group(1)}(.*)*")
        elif dynamic:
            route_segments.append(f":{dynamic.group(1)}")
        else:
            route_segments.append(segment)
    return "/" + "/".join(route_segments)


def frontend_modules(root: Path) -> tuple[list[FrontendModule], list[FrontendPage]]:
    modules: list[FrontendModule] = []
    all_pages: list[FrontendPage] = []
    for name in frontend_module_names(root):
        path = root / "front" / Path(*name.split("/"))
        capabilities = [
            item for item in FRONTEND_CAPABILITIES
            if (path / item).is_file()
            or contains_source(path / item, frozenset({".ts", ".vue"}))
        ]
        pages: list[FrontendPage] = []
        pages_root = path / "pages"
        if pages_root.is_dir():
            for page in sorted(pages_root.rglob("*.vue")):
                info: FrontendPage = {
                    "module": name,
                    "file": relative(page, root),
                    "route_hint": page_route_hint(name, page, pages_root),
                }
                pages.append(info)
                all_pages.append(info)
        layer = cast(Literal["core", "app", "bridge"], name.split("/", 1)[0])
        modules.append(
            {
                "name": name,
                "layer": layer,
                "path": relative(path, root),
                "exists": path.is_dir(),
                "capabilities": sorted(capabilities),
                "pages": pages,
            }
        )
    return modules, sorted(all_pages, key=lambda item: (item["route_hint"], item["file"]))


def production_frontend_files(root: Path) -> list[Path]:
    """Return statically analyzable Vue and TypeScript production files."""

    files: list[Path] = []
    for layer in ("core", "app", "bridge"):
        layer_root = root / "front" / layer
        if not layer_root.exists():
            continue
        for path in layer_root.rglob("*"):
            if path.is_file() and path.suffix in {".ts", ".vue"}:
                files.append(path)
    return sorted(files)


def frontend_module_key(path: Path, root: Path) -> str:
    parts = path.relative_to(root / "front").parts
    if len(parts) < 2:
        raise ValueError(f"Cannot derive a frontend module from {path}")
    return f"{parts[0]}/{Path(parts[1]).stem}"


_STATIC_FRONTEND_IMPORT = re.compile(
    r"(?:import|export)\s+(?:type\s+)?(?:[^\"']*?\sfrom\s*)?[\"']([^\"']+)[\"']"
)
_DYNAMIC_FRONTEND_IMPORT = re.compile(r"import\(\s*[\"']([^\"']+)[\"']\s*\)")


def frontend_import_specifiers(content: str) -> list[str]:
    """Extract static and literal dynamic ES module specifiers deterministically."""

    return sorted(
        set(_STATIC_FRONTEND_IMPORT.findall(content))
        | set(_DYNAMIC_FRONTEND_IMPORT.findall(content))
    )


def resolve_frontend_import(
    path: Path,
    specifier: str,
    root: Path,
) -> tuple[str, str] | None:
    """Resolve an internal import to its module and normalized alias."""

    front_root = root / "front"
    if specifier.startswith("@/"):
        relative_target = Path(specifier[2:])
    elif specifier.startswith("."):
        try:
            relative_target = (path.parent / specifier).resolve().relative_to(
                front_root.resolve()
            )
        except ValueError:
            return None
    else:
        return None

    parts = relative_target.parts
    if len(parts) < 2 or parts[0] not in {"core", "app", "bridge"}:
        return None
    module = f"{parts[0]}/{Path(parts[1]).stem}"
    normalized = "@/" + relative_target.as_posix()
    return module, normalized


def frontend_dependencies(root: Path) -> list[DependencyEdge]:
    edge_files: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path in production_frontend_files(root):
        source = frontend_module_key(path, root)
        content = path.read_text(encoding="utf-8")
        for specifier in frontend_import_specifiers(content):
            resolved = resolve_frontend_import(path, specifier, root)
            if resolved is None:
                continue
            target, _ = resolved
            if source != target:
                edge_files[(source, target)].add(relative(path, root))
    return [
        {"source": source, "target": target, "files": sorted(files)}
        for (source, target), files in sorted(edge_files.items())
    ]


def imported_modules(tree: ast.Module) -> list[str]:
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imports.append(node.module)
    return imports


def dependency_edges(root: Path, trees: dict[Path, ast.Module]) -> list[DependencyEdge]:
    edge_files: dict[tuple[str, str], set[str]] = defaultdict(set)
    for path, tree in trees.items():
        source = module_key(path, root)
        for imported in imported_modules(tree):
            parts = imported.split(".")
            if len(parts) < 2 or parts[0] not in {"core", "app", "bridge"}:
                continue
            target = ".".join(parts[:2])
            if source != target:
                edge_files[(source, target)].add(relative(path, root))
    return [
        {"source": source, "target": target, "files": sorted(files)}
        for (source, target), files in sorted(edge_files.items())
    ]


def is_domain_module(name: str) -> bool:
    return (
        name.startswith("app.")
        or name.startswith("bridge.")
        or name.startswith("app/")
        or name.startswith("bridge/")
    )


def strongly_connected_components(edges: list[DependencyEdge]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = defaultdict(set)
    nodes: set[str] = set()
    for edge in edges:
        source = edge["source"]
        target = edge["target"]
        if not is_domain_module(source) or not is_domain_module(target):
            continue
        nodes.update((source, target))
        adjacency[source].add(target)

    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def visit(module: str) -> None:
        nonlocal next_index
        indices[module] = next_index
        lowlinks[module] = next_index
        next_index += 1
        stack.append(module)
        on_stack.add(module)

        for target in sorted(adjacency[module]):
            if target not in indices:
                visit(target)
                lowlinks[module] = min(lowlinks[module], lowlinks[target])
            elif target in on_stack:
                lowlinks[module] = min(lowlinks[module], indices[target])

        if lowlinks[module] != indices[module]:
            return
        component: list[str] = []
        while stack:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == module:
                break
        if len(component) > 1:
            components.append(sorted(component))

    for module in sorted(nodes):
        if module not in indices:
            visit(module)
    return sorted(components)


def dependency_metrics(edges: list[DependencyEdge]) -> DependencyMetrics:
    domain_edges = [
        edge
        for edge in edges
        if is_domain_module(edge["source"]) and is_domain_module(edge["target"])
    ]
    pairs = {(edge["source"], edge["target"]) for edge in domain_edges}
    direct_cycles = sorted(
        [source, target]
        for source, target in pairs
        if source < target and (target, source) in pairs
    )

    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for source, target in pairs:
        outgoing[source].add(target)
        incoming[target].add(source)

    def degrees(values: dict[str, set[str]]) -> list[ModuleDependencyDegree]:
        return sorted(
            (
                {"module": module, "count": len(modules), "modules": sorted(modules)}
                for module, modules in values.items()
            ),
            key=lambda item: (-item["count"], item["module"]),
        )

    return {
        "domain_edges": len(domain_edges),
        "direct_cycles": direct_cycles,
        "strongly_connected_components": strongly_connected_components(domain_edges),
        "fan_in": degrees(incoming),
        "fan_out": degrees(outgoing),
    }


def dotted_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = dotted_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def router_prefixes(tree: ast.Module) -> dict[str, str]:
    prefixes: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)) or not isinstance(node.value, ast.Call):
            continue
        if not dotted_name(node.value.func).endswith("APIRouter"):
            continue
        prefix = ""
        for keyword in node.value.keywords:
            if keyword.arg == "prefix" and isinstance(keyword.value, ast.Constant):
                if isinstance(keyword.value.value, str):
                    prefix = keyword.value.value
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                prefixes[target.id] = prefix
    return prefixes


def join_route(prefix: str, path: str) -> str:
    combined = "/".join(part.strip("/") for part in (prefix, path) if part.strip("/"))
    return f"/{combined}" if combined else "/"


def routes(root: Path, trees: dict[Path, ast.Module]) -> list[RouteInfo]:
    result: list[RouteInfo] = []
    for path, tree in trees.items():
        prefixes = router_prefixes(tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            authorized = any(dotted_name(dec.func if isinstance(dec, ast.Call) else dec).endswith("authorize") for dec in node.decorator_list)
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
                    continue
                method = decorator.func.attr.lower()
                if method not in HTTP_METHODS:
                    continue
                router_name = dotted_name(decorator.func.value)
                declared = ""
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    raw = decorator.args[0].value
                    if isinstance(raw, str):
                        declared = raw
                result.append(
                    {
                        "module": module_key(path, root),
                        "method": method.upper(),
                        "declared_path": join_route(prefixes.get(router_name, ""), declared),
                        "handler": node.name,
                        "authorized": authorized,
                        "file": relative(path, root),
                        "line": node.lineno,
                    }
                )
    return sorted(result, key=lambda item: (item["declared_path"], item["method"], item["file"], item["line"]))


def string_assignment(node: ast.stmt, name: str) -> str | None:
    if isinstance(node, ast.Assign):
        if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == name:
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    return None


def models(root: Path, trees: dict[Path, ast.Module]) -> list[ModelInfo]:
    result: list[ModelInfo] = []
    for path, tree in trees.items():
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            table: str | None = None
            for statement in node.body:
                table = string_assignment(statement, "__tablename__") or table
            if table is None:
                continue
            foreign_keys: set[str] = set()
            for child in ast.walk(node):
                if not isinstance(child, ast.Call) or not dotted_name(child.func).endswith("ForeignKey"):
                    continue
                if child.args and isinstance(child.args[0], ast.Constant):
                    value = child.args[0].value
                    if isinstance(value, str):
                        foreign_keys.add(value)
            result.append(
                {
                    "module": module_key(path, root),
                    "class_name": node.name,
                    "table": table,
                    "history_mixin": any(dotted_name(base).endswith("HistoryMixin") for base in node.bases),
                    "foreign_keys": sorted(foreign_keys),
                    "file": relative(path, root),
                    "line": node.lineno,
                }
            )
    return sorted(result, key=lambda item: (item["table"], item["class_name"]))


def constant_keyword(call: ast.Call, key: str) -> str | None:
    for keyword in call.keywords:
        if keyword.arg == key and isinstance(keyword.value, ast.Constant):
            value = keyword.value.value
            if isinstance(value, str):
                return value
    return None


def mcp_tools(root: Path, trees: dict[Path, ast.Module]) -> list[McpToolInfo]:
    result: list[McpToolInfo] = []
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not dotted_name(decorator.func).endswith("mcp_tool"):
                    continue
                namespace = ""
                if decorator.args and isinstance(decorator.args[0], ast.Constant):
                    value = decorator.args[0].value
                    if isinstance(value, str):
                        namespace = value
                result.append(
                    {
                        "module": module_key(path, root),
                        "namespace": namespace,
                        "name": constant_keyword(decorator, "name") or node.name,
                        "handler": node.name,
                        "file": relative(path, root),
                        "line": node.lineno,
                    }
                )
    return sorted(result, key=lambda item: (item["namespace"], item["name"], item["file"]))


def privileges(root: Path, trees: dict[Path, ast.Module]) -> list[PrivilegeInfo]:
    result: list[PrivilegeInfo] = []
    for path, tree in trees.items():
        if path.name != "privileges.py":
            continue
        for node in tree.body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value_node = node.value
            if not isinstance(value_node, ast.Constant) or not isinstance(value_node.value, str):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and re.fullmatch(r"[A-Z][A-Z0-9_]+", target.id):
                    result.append(
                        {
                            "module": module_key(path, root),
                            "constant": target.id,
                            "value": value_node.value,
                            "file": relative(path, root),
                            "line": node.lineno,
                        }
                    )
    return sorted(result, key=lambda item: (item["module"], item["constant"]))


def settings_map(root: Path) -> SettingsMap:
    settings_path = root / "back" / "core" / "settings.py"
    tree = parse_python(settings_path)
    declared: set[str] = set()
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "Settings":
            continue
        for statement in node.body:
            if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
                annotation = statement.annotation
                if isinstance(annotation, ast.Subscript):
                    annotation = annotation.value
                annotation_name = dotted_name(annotation)
                if annotation_name in {"ClassVar", "typing.ClassVar"}:
                    continue
                name = statement.target.id
                if re.fullmatch(r"[A-Z][A-Z0-9_]+", name):
                    declared.add(name)

    env_path = root / ".env.example"
    env_names: set[str] = set()
    if env_path.is_file():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^#?\s*([A-Z][A-Z0-9_]*)=", line.strip())
            if match:
                env_names.add(match.group(1))

    return {
        "declared": sorted(declared),
        "env_example": sorted(env_names),
        "missing_from_env_example": sorted(declared - env_names),
        "env_only": sorted(env_names - declared),
    }


def build_project_map(root: Path) -> ProjectMap:
    files = production_python_files(root)
    trees = {path: parse_python(path) for path in files}
    front_modules, pages = frontend_modules(root)
    dependencies = dependency_edges(root, trees)
    front_dependencies = frontend_dependencies(root)
    return {
        "schema_version": 3,
        "generated_by": "back/scripts/project_context.py",
        "backend": {
            "modules": backend_modules(root),
            "dependencies": dependencies,
            "dependency_metrics": dependency_metrics(dependencies),
            "routes": routes(root, trees),
            "models": models(root, trees),
            "mcp_tools": mcp_tools(root, trees),
            "privileges": privileges(root, trees),
        },
        "frontend": {
            "modules": front_modules,
            "dependencies": front_dependencies,
            "dependency_metrics": dependency_metrics(front_dependencies),
            "pages": pages,
        },
        "settings": settings_map(root),
    }


def md_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def md_list(values: list[str]) -> str:
    return ", ".join(f"`{md_cell(value)}`" for value in values) if values else "—"


def render_markdown(
    project: ProjectMap,
    language: Literal["fr", "en"] = "fr",
) -> str:
    backend = project["backend"]
    metrics = backend["dependency_metrics"]
    frontend = project["frontend"]
    frontend_metrics = frontend["dependency_metrics"]
    settings = project["settings"]

    def tr(french: str, english: str) -> str:
        return english if language == "en" else french

    yes = tr("oui", "yes")
    no = tr("non", "no")
    lines: list[str] = [
        tr(
            '<p align="right"><strong>Français</strong> · <a href="../../../en/architecture/generated/project-map.md">English</a></p>',
            '<p align="right"><a href="../../../fr/architecture/generated/project-map.md">Français</a> · <strong>English</strong></p>',
        ),
        "",
        tr("# Cartographie générée de Galaris", "# Generated Galaris Project Map"),
        "",
        tr(
            "> Généré par `back/scripts/project_context.py`. Ne pas modifier à la main.",
            "> Generated by `back/scripts/project_context.py`. Do not edit manually.",
        ),
        "",
        tr(
            "Cette vue est un index statique du code, pas une spécification métier. Les contrats et",
            "This view is a static index of the code, not a business specification. Contracts and",
        ),
        tr(
            "tests restent l’autorité sur le comportement.",
            "tests remain authoritative for behavior.",
        ),
        "",
        tr("## Résumé", "## Summary"),
        "",
        tr(
            f"- {len(backend['modules'])} modules backend déclarés ;",
            f"- {len(backend['modules'])} declared backend modules;",
        ),
        tr(
            f"- {len(frontend['modules'])} modules frontend déclarés ;",
            f"- {len(frontend['modules'])} declared frontend modules;",
        ),
        tr(
            f"- {len(backend['dependencies'])} arêtes de dépendance backend ;",
            f"- {len(backend['dependencies'])} backend dependency edges;",
        ),
        tr(
            f"- {len(frontend['dependencies'])} arêtes de dépendance frontend ;",
            f"- {len(frontend['dependencies'])} frontend dependency edges;",
        ),
        tr(
            f"- {metrics['domain_edges']} arêtes entre domaines `app`/`bridge` ;",
            f"- {metrics['domain_edges']} edges between `app`/`bridge` domains;",
        ),
        tr(
            f"- {len(metrics['direct_cycles'])} paires de domaines directement "
            "bidirectionnelles ;",
            f"- {len(metrics['direct_cycles'])} directly bidirectional domain pairs;",
        ),
        tr(
            f"- {len(metrics['strongly_connected_components'])} composantes fortement "
            "connexes ;",
            f"- {len(metrics['strongly_connected_components'])} strongly connected "
            "components;",
        ),
        tr(
            f"- {len(frontend_metrics['direct_cycles'])} paires frontend directement "
            "bidirectionnelles ;",
            f"- {len(frontend_metrics['direct_cycles'])} directly bidirectional frontend "
            "pairs;",
        ),
        tr(
            f"- {len(backend['routes'])} handlers HTTP/WebSocket détectés ;",
            f"- {len(backend['routes'])} detected HTTP/WebSocket handlers;",
        ),
        tr(
            f"- {len(backend['models'])} tables SQLAlchemy détectées ;",
            f"- {len(backend['models'])} detected SQLAlchemy tables;",
        ),
        tr(
            f"- {len(backend['mcp_tools'])} outils MCP natifs détectés ;",
            f"- {len(backend['mcp_tools'])} detected native MCP tools;",
        ),
        tr(
            f"- {len(frontend['pages'])} pages Vue détectées.",
            f"- {len(frontend['pages'])} detected Vue pages.",
        ),
        "",
        tr("## Modules backend", "## Backend Modules"),
        "",
        tr(
            "| Module | Couche | Conditionnel | Existe | Capacités |",
            "| Module | Layer | Conditional | Exists | Capabilities |",
        ),
        "|---|---|---:|---:|---|",
    ]
    for module in backend["modules"]:
        lines.append(
            f"| `{module['name']}` | {module['layer']} | {yes if module['conditional'] else no} | "
            f"{yes if module['exists'] else f'**{no}**'} | {md_list(module['capabilities'])} |"
        )

    lines.extend(
        [
            "",
            tr("## Modules frontend", "## Frontend Modules"),
            "",
            tr(
                "| Module | Existe | Capacités | Pages |",
                "| Module | Exists | Capabilities | Pages |",
            ),
            "|---|---:|---|---:|",
        ]
    )
    for module in frontend["modules"]:
        lines.append(
            f"| `{module['name']}` | {yes if module['exists'] else f'**{no}**'} | "
            f"{md_list(module['capabilities'])} | {len(module['pages'])} |"
        )

    lines.extend(
        [
            "",
            tr(
                "## Dépendances backend inter-modules",
                "## Inter-module Backend Dependencies",
            ),
            "",
            tr("| Source | Cible | Fichiers |", "| Source | Target | Files |"),
            "|---|---|---|",
        ]
    )
    for edge in backend["dependencies"]:
        lines.append(f"| `{edge['source']}` | `{edge['target']}` | {md_list(edge['files'])} |")

    lines.extend(
        [
            "",
            tr(
                "## Dépendances frontend inter-modules",
                "## Inter-module Frontend Dependencies",
            ),
            "",
            tr("| Source | Cible | Fichiers |", "| Source | Target | Files |"),
            "|---|---|---|",
        ]
    )
    for edge in frontend["dependencies"]:
        lines.append(
            f"| `{edge['source']}` | `{edge['target']}` | {md_list(edge['files'])} |"
        )

    lines.extend(
        [
            "",
            tr(
                "## Métriques de couplage des domaines backend",
                "## Backend Domain Coupling Metrics",
            ),
            "",
            tr(
                "> Ces métriques portent sur les arêtes entre modules `app.*` et `bridge.*`.",
                "> These metrics cover edges between `app.*` and `bridge.*` modules.",
            ),
            tr(
                "> Le manifeste et la baseline d’architecture déterminent les régressions admises.",
                "> The architecture manifest and baseline determine the accepted regressions.",
            ),
            "",
            "### Fan-out",
            "",
            tr("| Module | Nombre | Dépendances |", "| Module | Count | Dependencies |"),
            "|---|---:|---|",
        ]
    )
    for degree in metrics["fan_out"]:
        lines.append(
            f"| `{degree['module']}` | {degree['count']} | {md_list(degree['modules'])} |"
        )

    lines.extend(
        [
            "",
            "### Fan-in",
            "",
            tr("| Module | Nombre | Dépendants |", "| Module | Count | Dependents |"),
            "|---|---:|---|",
        ]
    )
    for degree in metrics["fan_in"]:
        lines.append(
            f"| `{degree['module']}` | {degree['count']} | {md_list(degree['modules'])} |"
        )

    lines.extend(
        [
            "",
            tr("### Cycles directs", "### Direct Cycles"),
            "",
        ]
    )
    if metrics["direct_cycles"]:
        lines.extend(
            f"- `{source}` ↔ `{target}`"
            for source, target in metrics["direct_cycles"]
        )
    else:
        lines.append(tr("Aucun cycle direct détecté.", "No direct cycle detected."))

    lines.extend(
        [
            "",
            tr(
                "### Composantes fortement connexes",
                "### Strongly Connected Components",
            ),
            "",
        ]
    )
    if metrics["strongly_connected_components"]:
        lines.extend(
            f"- {md_list(component)}"
            for component in metrics["strongly_connected_components"]
        )
    else:
        lines.append(
            tr("Aucune composante cyclique détectée.", "No cyclic component detected.")
        )

    lines.extend(
        [
            "",
            tr(
                "## Métriques de couplage des domaines frontend",
                "## Frontend Domain Coupling Metrics",
            ),
            "",
            tr(
                "> Ces métriques portent sur les imports entre modules `app/*` et `bridge/*`.",
                "> These metrics cover imports between `app/*` and `bridge/*` modules.",
            ),
            "",
            "### Fan-out frontend",
            "",
            tr("| Module | Nombre | Dépendances |", "| Module | Count | Dependencies |"),
            "|---|---:|---|",
        ]
    )
    for degree in frontend_metrics["fan_out"]:
        lines.append(
            f"| `{degree['module']}` | {degree['count']} | {md_list(degree['modules'])} |"
        )
    lines.extend(
        [
            "",
            "### Fan-in frontend",
            "",
            tr("| Module | Nombre | Dépendants |", "| Module | Count | Dependents |"),
            "|---|---:|---|",
        ]
    )
    for degree in frontend_metrics["fan_in"]:
        lines.append(
            f"| `{degree['module']}` | {degree['count']} | {md_list(degree['modules'])} |"
        )
    lines.extend(["", tr("### Cycles directs frontend", "### Direct Frontend Cycles"), ""])
    if frontend_metrics["direct_cycles"]:
        lines.extend(
            f"- `{source}` ↔ `{target}`"
            for source, target in frontend_metrics["direct_cycles"]
        )
    else:
        lines.append(tr("Aucun cycle direct détecté.", "No direct cycle detected."))
    lines.extend(
        [
            "",
            tr(
                "### Composantes fortement connexes frontend",
                "### Strongly Connected Frontend Components",
            ),
            "",
        ]
    )
    if frontend_metrics["strongly_connected_components"]:
        lines.extend(
            f"- {md_list(component)}"
            for component in frontend_metrics["strongly_connected_components"]
        )
    else:
        lines.append(
            tr("Aucune composante cyclique détectée.", "No cyclic component detected.")
        )

    lines.extend(
        [
            "",
            tr("## Routes backend déclarées", "## Declared Backend Routes"),
            "",
            tr(
                "> Les préfixes ajoutés lors de l’agrégation de routers ne peuvent pas tous être",
                "> Prefixes added while aggregating routers cannot all be reconstructed",
            ),
            tr(
                "> reconstruits statiquement ; `declared_path` décrit le préfixe local détecté.",
                "> statically; `declared_path` describes the detected local prefix.",
            ),
            "",
            tr(
                "| Méthode | Chemin déclaré | Module | Handler | RBAC local | Source |",
                "| Method | Declared Path | Module | Handler | Local RBAC | Source |",
            ),
            "|---|---|---|---|---:|---|",
        ]
    )
    for route in backend["routes"]:
        source = f"{route['file']}:{route['line']}"
        lines.append(
            f"| {route['method']} | `{md_cell(route['declared_path'])}` | `{route['module']}` | "
            f"`{route['handler']}` | {yes if route['authorized'] else no} | `{source}` |"
        )

    lines.extend(
        [
            "",
            tr("## Modèles SQLAlchemy", "## SQLAlchemy Models"),
            "",
            tr(
                "| Table | Classe | Module | Historisée | Clés étrangères | Source |",
                "| Table | Class | Module | Versioned | Foreign Keys | Source |",
            ),
            "|---|---|---|---:|---|---|",
        ]
    )
    for model in backend["models"]:
        source = f"{model['file']}:{model['line']}"
        lines.append(
            f"| `{model['table']}` | `{model['class_name']}` | `{model['module']}` | "
            f"{yes if model['history_mixin'] else no} | "
            f"{md_list(model['foreign_keys'])} | `{source}` |"
        )

    lines.extend(
        [
            "",
            tr("## Outils MCP natifs", "## Native MCP Tools"),
            "",
            tr(
                "| Nom | Namespace | Module | Handler | Source |",
                "| Name | Namespace | Module | Handler | Source |",
            ),
            "|---|---|---|---|---|",
        ]
    )
    for tool in backend["mcp_tools"]:
        source = f"{tool['file']}:{tool['line']}"
        lines.append(
            f"| `{tool['name']}` | `{tool['namespace']}` | `{tool['module']}` | "
            f"`{tool['handler']}` | `{source}` |"
        )

    lines.extend(
        [
            "",
            tr("## Privilèges déclarés", "## Declared Privileges"),
            "",
            tr(
                "| Constante | Module | Libellé | Source |",
                "| Constant | Module | Label | Source |",
            ),
            "|---|---|---|---|",
        ]
    )
    for privilege in backend["privileges"]:
        source = f"{privilege['file']}:{privilege['line']}"
        lines.append(
            f"| `{privilege['constant']}` | `{privilege['module']}` | "
            f"{md_cell(privilege['value'])} | `{source}` |"
        )

    lines.extend(
        [
            "",
            tr("## Pages frontend", "## Frontend Pages"),
            "",
            tr(
                "| Route indicative | Module | Source |",
                "| Indicative Route | Module | Source |",
            ),
            "|---|---|---|",
        ]
    )
    for page in frontend["pages"]:
        lines.append(f"| `{page['route_hint']}` | `{page['module']}` | `{page['file']}` |")

    lines.extend(
        [
            "",
            tr("## Configuration", "## Configuration"),
            "",
            tr(
                f"- Settings déclarés : {len(settings['declared'])}.",
                f"- Declared settings: {len(settings['declared'])}.",
            ),
            tr(
                f"- Variables dans `.env.example` : {len(settings['env_example'])}.",
                f"- Variables in `.env.example`: {len(settings['env_example'])}.",
            ),
            tr(
                "- Settings sans entrée `.env.example` : "
                f"{md_list(settings['missing_from_env_example'])}.",
                "- Settings without an `.env.example` entry: "
                f"{md_list(settings['missing_from_env_example'])}.",
            ),
            tr(
                "- Entrées `.env.example` sans champ direct dans `Settings` : "
                f"{md_list(settings['env_only'])}.",
                "- `.env.example` entries without a direct `Settings` field: "
                f"{md_list(settings['env_only'])}.",
            ),
            "",
        ]
    )
    return "\n".join(lines)


def rendered_files(root: Path) -> dict[Path, str]:
    project = build_project_map(root)
    serialized = json.dumps(project, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    outputs: dict[Path, str] = {}
    for language in ("fr", "en"):
        output_dir = root / "docs" / language / "architecture" / "generated"
        outputs[output_dir / "project-map.json"] = serialized
        outputs[output_dir / "project-map.md"] = render_markdown(project, language)
    return outputs


def write_outputs(outputs: dict[Path, str]) -> None:
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"generated {path}")


def check_outputs(outputs: dict[Path, str]) -> bool:
    stale: list[Path] = []
    for path, expected in outputs.items():
        actual = path.read_text(encoding="utf-8") if path.is_file() else None
        if actual != expected:
            stale.append(path)
    if stale:
        for path in stale:
            print(f"stale or missing: {path}", file=sys.stderr)
        print("Run `make project-context` to regenerate the project map.", file=sys.stderr)
        return False
    print("project context is up to date")
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root; defaults to the script's repository")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail instead of writing when output differs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_root = cast(str | None, args.root)
    root = Path(raw_root).resolve() if raw_root else Path(__file__).resolve().parents[2]
    outputs = rendered_files(root)
    if cast(bool, args.check):
        return 0 if check_outputs(outputs) else 1
    write_outputs(outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
