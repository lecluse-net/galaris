"""Prevent orchestration from acquiring runtime-specific branches again."""

import ast
from pathlib import Path

from app.agent.registry import all_driver_specs
from app.harnesses.registry import all_providers


def test_generic_orchestration_does_not_branch_on_concrete_harness_names():
    root = Path(__file__).resolve().parents[1]
    names = {spec.code for spec in all_driver_specs()} | {provider.code for provider in all_providers()}
    paths = [*root.joinpath("app/agent").glob("*.py"), *root.joinpath("app/task").glob("*.py"),
             root / "app/tools/mcp_loader.py"]
    violations = []
    for path in paths:
        if path.name == "registry.py":
            continue  # The explicit composition registry owns the default contribution.
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Compare):
                constants = {item.value for item in ast.walk(node) if isinstance(item, ast.Constant) and isinstance(item.value, str)}
                if constants & names:
                    violations.append(f"{path.relative_to(root)}:{node.lineno}: {sorted(constants & names)}")
    assert not violations, "Use the shared capability/checkpoint contract:\n" + "\n".join(violations)
