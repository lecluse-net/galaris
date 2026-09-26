"""Check durable Galaris architecture and repository knowledge contracts."""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
from pathlib import Path
from typing import cast

try:
    from .architecture_contracts import (
        BASELINE_PATH,
        build_architecture_baseline,
        check_architecture_contracts,
        load_architecture_policy,
        serialize_architecture_baseline,
    )
    from .frontend_architecture_contracts import (
        FRONTEND_BASELINE_PATH,
        build_frontend_architecture_baseline,
        check_frontend_architecture_contracts,
        serialize_frontend_architecture_baseline,
    )
    from .docs_i18n_check import check_documentation_locales
    from .project_context import (
        backend_modules,
        frontend_module_names,
        imported_modules,
        parse_python,
        production_python_files,
        relative,
    )
except ImportError:  # Direct execution from back/scripts.
    from architecture_contracts import (
        BASELINE_PATH,
        build_architecture_baseline,
        check_architecture_contracts,
        load_architecture_policy,
        serialize_architecture_baseline,
    )
    from frontend_architecture_contracts import (
        FRONTEND_BASELINE_PATH,
        build_frontend_architecture_baseline,
        check_frontend_architecture_contracts,
        serialize_frontend_architecture_baseline,
    )
    from docs_i18n_check import check_documentation_locales
    from project_context import (
        backend_modules,
        frontend_module_names,
        imported_modules,
        parse_python,
        production_python_files,
        relative,
    )


ALLOWED_APP_TO_BRIDGE_FILES = frozenset(
    {
        "back/app/audio/mcp.py",  # Public YouTube transcript adapter.
        "back/app/file_share/bridges.py",  # File-client composition registry.
        "back/app/file_share/file_share_service.py",  # Nextcloud file transport.
    }
)
REQUIRED_ARCHITECTURE_DOCS = (
    "docs/fr/architecture/README.md",
    "docs/fr/architecture/invariants.md",
    "docs/fr/architecture/state-machines.md",
    "docs/fr/architecture/flows/agent-execution.md",
    "docs/fr/architecture/flows/messaging.md",
    "docs/fr/architecture/flows/process.md",
    "docs/fr/architecture/flows/media-resources.md",
    "docs/fr/architecture/flows/llm-provider-bridges.md",
    "docs/fr/architecture/generated/project-map.json",
    "docs/fr/architecture/generated/project-map.md",
    "docs/en/architecture/README.md",
    "docs/en/architecture/invariants.md",
    "docs/en/architecture/state-machines.md",
    "docs/en/architecture/flows/agent-execution.md",
    "docs/en/architecture/flows/messaging.md",
    "docs/en/architecture/flows/process.md",
    "docs/en/architecture/flows/media-resources.md",
    "docs/en/architecture/flows/llm-provider-bridges.md",
    "docs/en/architecture/generated/project-map.json",
    "docs/en/architecture/generated/project-map.md",
    "back/architecture.toml",
    "back/architecture-baseline.json",
    "front/architecture-baseline.json",
    "project/decisions/0001-postgresql-source-of-truth.md",
    "project/decisions/0002-agent-driver-boundary.md",
    "project/decisions/0003-canonical-messaging-bridges.md",
    "project/decisions/0004-declarative-atlas-schema.md",
    "project/decisions/0014-llm-provider-bridges.md",
    "project/decisions/0042-progressive-module-coupling-contracts.md",
    "project/plans/README.md",
)
PLAN_STATUSES = frozenset(
    {
        "design",
        "approved",
        "in-progress",
        "partial",
    }
)


def check_declared_modules(root: Path) -> list[str]:
    errors: list[str] = []
    for module in backend_modules(root):
        if not module["exists"]:
            errors.append(f"backend module {module['name']} has no package at {module['path']}")
    for name in frontend_module_names(root):
        path = root / "front" / Path(*name.split("/"))
        if not path.is_dir():
            errors.append(f"frontend module {name} has no directory at {relative(path, root)}")
    return errors


def imported_prefixes(tree: ast.Module) -> set[str]:
    return set(imported_modules(tree))


def check_python_boundaries(root: Path) -> list[str]:
    errors: list[str] = []
    for path in production_python_files(root):
        tree = parse_python(path)
        source = relative(path, root)
        module_parts = path.relative_to(root / "back").parts
        layer = module_parts[0]
        module = f"{module_parts[0]}.{Path(module_parts[1]).stem}" if len(module_parts) > 1 else layer
        imports = imported_prefixes(tree)

        if layer == "core":
            forbidden = sorted(name for name in imports if name == "app" or name.startswith("app.") or name == "bridge" or name.startswith("bridge."))
            for target in forbidden:
                errors.append(f"{source}: core must not import {target}")

        if layer == "bridge":
            forbidden = sorted(
                name
                for name in imports
                if name == "app.harness"
                or name.startswith("app.harness.")
                or name == "app.task"
                or name.startswith("app.task.")
            )
            for target in forbidden:
                errors.append(f"{source}: bridges must not couple to runtime/task detail {target}")

        if layer == "app":
            bridge_imports = sorted(name for name in imports if name == "bridge" or name.startswith("bridge."))
            if bridge_imports and source not in ALLOWED_APP_TO_BRIDGE_FILES:
                errors.append(
                    f"{source}: app-to-bridge import requires an explicit composition exception "
                    f"({', '.join(bridge_imports)})"
                )

        if module == "app.agent":
            for target in sorted(imports):
                if target == "app.task" or target.startswith("app.task."):
                    errors.append(f"{source}: app.agent must use AgentTaskPort instead of {target}")
                if target == "pydantic_ai" or target.startswith("pydantic_ai."):
                    errors.append(f"{source}: app.agent contracts must not depend on Pydantic AI ({target})")

        if module == "app.task":
            for target in sorted(imports):
                if target == "pydantic_ai" or target.startswith("pydantic_ai."):
                    errors.append(f"{source}: app.task must remain runtime-independent ({target})")
                if target == "app.harness" or target.startswith("app.harness."):
                    errors.append(f"{source}: app.task must call app.agent, not {target}")
    return errors


def check_frontend_bridge_ownership(root: Path) -> list[str]:
    """Keep Hermes-specific product UI inside its frontend bridge module."""

    errors: list[str] = []
    app_root = root / "front" / "app"
    for path in sorted(app_root.rglob("*")):
        if path.suffix not in {".ts", ".vue"} or not path.is_file():
            continue
        if re.search(r"\bhermes\b", path.read_text(encoding="utf-8"), re.IGNORECASE):
            errors.append(
                f"{relative(path, root)}: Hermes-specific UI belongs in front/bridge/hermes"
            )
    return errors


def skill_frontmatter(path: Path) -> tuple[dict[str, str], str] | None:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        return None
    try:
        end = lines.index("---", 1)
    except ValueError:
        return None
    values: dict[str, str] = {}
    for line in lines[1:end]:
        match = re.fullmatch(r"([a-zA-Z_][a-zA-Z0-9_-]*):\s*(.*)", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
        elif line.strip():
            values["<invalid>"] = line
    return values, content


def _contains_versioned_path(
    root: Path,
    path: str,
    *,
    allowed_local_files: frozenset[str] = frozenset(),
) -> bool:
    """Return whether Git tracks a file below ``path``.

    Developer-local ignored settings must not make the repository architecture gate depend on
    the workstation. Outside a Git checkout, retain the conservative filesystem check used by
    isolated fixtures and source archives.
    """

    def contains_unapproved_local_file() -> bool:
        candidate = root / path
        if not candidate.is_dir() or not allowed_local_files:
            return candidate.exists()
        local_files = {
            item.relative_to(candidate).as_posix()
            for item in candidate.rglob("*")
            if item.is_file() or item.is_symlink()
        }
        return bool(local_files - allowed_local_files)

    manifest = root / ".documentation-tracked-paths"
    if manifest.is_file():
        paths = manifest.read_text(encoding="utf-8").split("\0")
        return any(item == path or item.startswith(f"{path}/") for item in paths)

    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", path],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return contains_unapproved_local_file()
    if result.returncode != 0:
        return contains_unapproved_local_file()
    return bool(result.stdout.strip())


def check_skills(root: Path) -> list[str]:
    errors: list[str] = []
    if not (root / "AGENTS.md").is_file():
        errors.append("AGENTS.md is missing")
    if _contains_versioned_path(root, "CLAUDE.md"):
        errors.append("legacy CLAUDE.md must not exist")
    if _contains_versioned_path(
        root,
        ".claude",
        allowed_local_files=frozenset({"settings.local.json"}),
    ):
        errors.append("legacy .claude directory must not exist")
    if _contains_versioned_path(root, ".codex/skills"):
        errors.append("legacy .codex/skills links must not exist; use .agents/skills")

    skills_root = root / ".agents" / "skills"
    if not skills_root.is_dir():
        return errors + ["missing .agents/skills"]

    seen_names: set[str] = set()
    for directory in sorted(path for path in skills_root.iterdir() if path.is_dir()):
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"{relative(directory, root)} has no SKILL.md")
            continue
        parsed = skill_frontmatter(skill_file)
        if parsed is None:
            errors.append(f"{relative(skill_file, root)} has invalid frontmatter delimiters")
            continue
        frontmatter, content = parsed
        if set(frontmatter) != {"name", "description"}:
            errors.append(
                f"{relative(skill_file, root)} frontmatter must contain only name and description"
            )
        name = frontmatter.get("name", "")
        description = frontmatter.get("description", "")
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append(f"{relative(skill_file, root)} has invalid skill name {name!r}")
        if name != directory.name:
            errors.append(f"skill directory {directory.name!r} must match frontmatter name {name!r}")
        if name in seen_names:
            errors.append(f"duplicate skill name {name!r}")
        seen_names.add(name)
        if len(description) < 20:
            errors.append(f"skill {name!r} needs a more informative description")
        if "TODO" in content:
            errors.append(f"skill {name!r} still contains TODO placeholders")
        openai_yaml = directory / "agents" / "openai.yaml"
        if openai_yaml.is_file() and f"${name}" not in openai_yaml.read_text(encoding="utf-8"):
            errors.append(f"{relative(openai_yaml, root)} default prompt must mention ${name}")
    return errors


def plan_index_entries(index: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    pattern = re.compile(
        r"^\|\s*\[([^\]]+\.md)\]\(([^)]+\.md)\)\s*\|\s*`([a-z-]+)`\s*\|"
    )
    for line in index.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line)
        if match and match.group(1) == match.group(2):
            entries[match.group(1)] = match.group(3)
    return entries


def check_plans(root: Path) -> list[str]:
    plans_root = root / "project" / "plans"
    index = plans_root / "README.md"
    if not index.is_file():
        return ["project/plans/README.md is missing"]
    entries = plan_index_entries(index)
    files = {path.name for path in plans_root.glob("*.md") if path.name != "README.md"}
    errors: list[str] = []
    for missing in sorted(files - set(entries)):
        errors.append(f"plan {missing} is not indexed in project/plans/README.md")
    for unknown in sorted(set(entries) - files):
        errors.append(f"project/plans/README.md references missing plan {unknown}")
    for filename, status in sorted(entries.items()):
        if status not in PLAN_STATUSES:
            errors.append(f"plan {filename} has unsupported status {status!r}")
    return errors


def check_docs(root: Path) -> list[str]:
    errors = [
        f"missing architecture document {path}"
        for path in REQUIRED_ARCHITECTURE_DOCS
        if not (root / path).is_file()
    ]
    errors.extend(check_documentation_locales(root))
    return errors


def check_llm_provider_ownership(root: Path) -> list[str]:
    """Keep product profiles and integrations out of the canonical LLM domain."""

    errors: list[str] = []
    llm_root = root / "back" / "app" / "llm"
    for path in sorted(llm_root.rglob("*.py")):
        if "tests" in path.parts:
            continue
        tree = parse_python(path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr if isinstance(function, ast.Attribute) else ""
            )
            if name == "ProviderProfile":
                errors.append(
                    f"{relative(path, root)}: provider profiles must be declared in bridge.*"
                )
    return errors


def run_checks(root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(check_declared_modules(root))
    errors.extend(check_python_boundaries(root))
    errors.extend(check_frontend_bridge_ownership(root))
    errors.extend(check_llm_provider_ownership(root))
    errors.extend(check_architecture_contracts(root))
    errors.extend(check_frontend_architecture_contracts(root))
    errors.extend(check_skills(root))
    errors.extend(check_plans(root))
    errors.extend(check_docs(root))
    return sorted(errors)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Repository root; defaults to the script's repository")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Replace the progressive architecture baseline with the current graph",
    )
    parser.add_argument("--output", type=Path, help="Output root (defaults to --root)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    raw_root = cast(str | None, args.root)
    root = Path(raw_root).resolve() if raw_root else Path(__file__).resolve().parents[2]
    output_root = Path(args.output).resolve() if args.output else root
    if cast(bool, args.update_baseline):
        policy = load_architecture_policy(root)
        baseline = build_architecture_baseline(root, policy)
        (output_root / BASELINE_PATH).parent.mkdir(parents=True, exist_ok=True)
        (output_root / BASELINE_PATH).write_text(
            serialize_architecture_baseline(baseline), encoding="utf-8"
        )
        print(f"updated {BASELINE_PATH}")
        frontend_baseline = build_frontend_architecture_baseline(root)
        frontend_path = output_root / FRONTEND_BASELINE_PATH
        frontend_path.parent.mkdir(parents=True, exist_ok=True)
        frontend_path.write_text(
            serialize_frontend_architecture_baseline(frontend_baseline),
            encoding="utf-8",
        )
        print(f"updated {FRONTEND_BASELINE_PATH}")
        return 0
    errors = run_checks(root)
    if errors:
        for error in errors:
            print(f"architecture error: {error}")
        return 1
    print("architecture contracts are satisfied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
