import asyncio
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from core.database import get_db_session, load_models


def _resolve_test_path(module_path: str) -> Path:
    """Resolve the manual test file path.

    - Prefix simple names with /app/tests/manual/.
    - Add the .py extension when it is omitted.
    """
    target = Path(module_path)
    if not target.is_absolute():
        if "/" not in module_path:
            target = Path("/app") / "tests" / "manual" / target
        else:
            target = Path("/app") / target

    # Try the .py extension when it is missing and the file does not exist.
    if not target.suffix and not target.exists():
        target_with_ext = target.with_suffix(".py")
        if target_with_ext.exists():
            return target_with_ext

    return target


def import_module_from_path(module_path: str) -> ModuleType:
    """Import a Python module from a file path."""
    target = _resolve_test_path(module_path)

    target = target.resolve()
    if not target.exists():
        raise FileNotFoundError(f"Manual test file not found: {target}")

    module_name = target.stem
    spec = importlib.util.spec_from_file_location(module_name, target)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load the module from {target}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


async def run_async_test(module: ModuleType) -> None:
    """Run the module's asynchronous main() function in a database session."""
    async with get_db_session():
        await module.main()


def main() -> None:
    """Run the manual-test command-line entry point."""
    if len(sys.argv) < 2:
        print("Usage: python scripts/manual_test.py <test_file_path>")
        print("Example: python scripts/manual_test.py tests/manual/test_pydantic_ai_simple.py")
        sys.exit(1)

    test_path = sys.argv[1]

    # Ensure /app is available for the project's absolute imports.
    if "/app" not in sys.path:
        sys.path.insert(0, "/app")

    load_models()

    try:
        module = import_module_from_path(test_path)
    except Exception:
        sys.exit(1)

    if hasattr(module, "main"):
        test_main: Any = module.main
        if inspect.iscoroutinefunction(test_main):
            asyncio.run(run_async_test(module))
        else:
            test_main()


if __name__ == "__main__":
    main()
