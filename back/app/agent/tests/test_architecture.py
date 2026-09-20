from __future__ import annotations

import ast
from pathlib import Path


BACK_ROOT = Path(__file__).resolve().parents[3]


def _production_python(root: Path) -> list[Path]:
    return [
        path
        for path in root.rglob("*.py")
        if "tests" not in path.parts and "__pycache__" not in path.parts
    ]


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


def test_generic_agent_domain_has_no_task_or_pydantic_ai_dependency() -> None:
    violations: list[str] = []
    for path in _production_python(BACK_ROOT / "app" / "agent"):
        for module in _imports(path):
            if module == "app.task" or module.startswith("app.task."):
                violations.append(f"{path.relative_to(BACK_ROOT)} -> {module}")
            if module == "pydantic_ai" or module.startswith("pydantic_ai."):
                violations.append(f"{path.relative_to(BACK_ROOT)} -> {module}")
    assert violations == []


def test_concrete_drivers_never_import_task_domain() -> None:
    violations: list[str] = []
    for root in (
        BACK_ROOT / "app" / "harness",
        BACK_ROOT / "bridge" / "hermes",
    ):
        for path in _production_python(root):
            for module in _imports(path):
                if module == "app.task" or module.startswith("app.task."):
                    violations.append(f"{path.relative_to(BACK_ROOT)} -> {module}")
    assert violations == []


def test_concrete_runtime_imports_are_restricted_to_the_registry() -> None:
    violations: list[str] = []
    for root in (BACK_ROOT / "app", BACK_ROOT / "core"):
        for path in _production_python(root):
            relative = path.relative_to(BACK_ROOT)
            for module in _imports(path):
                if module == "app.harness" or module.startswith("app.harness."):
                    violations.append(f"{relative} -> {module}")
                if (
                    module == "bridge.hermes"
                    or module.startswith("bridge.hermes.")
                ):
                    violations.append(f"{relative} -> {module}")
    assert violations == []


def test_core_never_depends_on_app_or_bridge() -> None:
    violations: list[str] = []
    for path in _production_python(BACK_ROOT / "core"):
        for module in _imports(path):
            if module == "app" or module.startswith("app."):
                violations.append(f"{path.relative_to(BACK_ROOT)} -> {module}")
            if module == "bridge" or module.startswith("bridge."):
                violations.append(f"{path.relative_to(BACK_ROOT)} -> {module}")
    assert violations == []


def test_application_mcp_functions_reuse_the_loader_database_context() -> None:
    """Native MCP functions are services, not database-session boundaries."""

    violations: list[str] = []
    for root in (BACK_ROOT / "app", BACK_ROOT / "bridge"):
        for path in root.rglob("mcp.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module == "core.database":
                    if any(alias.name == "get_db_session" for alias in node.names):
                        violations.append(str(path.relative_to(BACK_ROOT)))
                elif (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "get_db_session"
                ):
                    violations.append(str(path.relative_to(BACK_ROOT)))
    assert sorted(set(violations)) == []


def test_generic_agent_api_has_no_hermes_configuration_fields() -> None:
    """Only the temporary ORM columns may retain legacy Hermes storage."""

    for relative in ("schemas.py", "agent_service.py", "router.py"):
        source = (BACK_ROOT / "app" / "agent" / relative).read_text(encoding="utf-8")
        assert "hermes_" not in source, relative


def test_generic_driver_registry_does_not_declare_hermes() -> None:
    source = (BACK_ROOT / "app" / "agent" / "registry.py").read_text(
        encoding="utf-8"
    )
    assert "hermes" not in source.lower()
