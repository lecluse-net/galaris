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


def test_messenger_uses_only_the_public_memory_surface() -> None:
    violations: list[str] = []
    for path in _production_python(BACK_ROOT / "app" / "messenger"):
        for module in _imports(path):
            if module.startswith("app.memory") and module not in {
                "app.memory",
                "app.memory.contracts",
            }:
                violations.append(
                    f"{path.relative_to(BACK_ROOT)} -> {module}"
                )
    assert violations == []


def test_bridges_never_import_memory() -> None:
    violations: list[str] = []
    for bridge in ("matrix", "nextcloud", "one_bot", "telegram", "whatsapp"):
        for path in _production_python(BACK_ROOT / "bridge" / bridge):
            for module in _imports(path):
                if module == "app.memory" or module.startswith("app.memory."):
                    violations.append(
                        f"{path.relative_to(BACK_ROOT)} -> {module}"
                    )
    assert violations == []
