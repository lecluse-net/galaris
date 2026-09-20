"""Process-engine registry without concrete bridge imports."""

from __future__ import annotations

from core.i18n import render_prompt, t

from .engine import ProcessEngine

_engines: dict[str, ProcessEngine] = {}
_default_code = "fake"


def register(engine: ProcessEngine, *, default: bool = False) -> None:
    global _default_code
    if not engine.code.strip():
        raise ValueError(t("process.errors.engine_code_required"))
    _engines[engine.code] = engine
    if default:
        _default_code = engine.code


def unregister(code: str) -> None:
    _engines.pop(code, None)


def set_default(code: str) -> None:
    global _default_code
    if code not in _engines:
        raise LookupError(render_prompt(
            t("process.errors.engine_not_configured"), code=code
        ))
    _default_code = code


def get(code: str | None = None) -> ProcessEngine:
    resolved = code or _default_code
    engine = _engines.get(resolved)
    if engine is None:
        raise LookupError(render_prompt(
            t("process.errors.engine_not_configured"), code=resolved
        ))
    return engine


def codes() -> tuple[str, ...]:
    return tuple(sorted(_engines))


def clear() -> None:
    _engines.clear()
