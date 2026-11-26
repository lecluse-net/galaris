"""Strict provider registry loaded at the composition boundary."""

from __future__ import annotations

import importlib
from typing import cast

from .contracts import HarnessProvider


_PROVIDERS: dict[str, HarnessProvider] = {}
_RETIRED_CODES: set[str] = set()
_loaded = False


class UnknownHarnessProviderError(LookupError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Unknown Harness provider: {code!r}.")


def register_provider(provider: HarnessProvider) -> None:
    code = provider.code.strip().lower()
    if not code or code != provider.code:
        raise ValueError(f"Harness provider codes must be normalized: {provider.code!r}.")
    limit = provider.max_parallel_tasks
    if limit is not None and (type(limit) is not int or limit < 1):
        raise ValueError(
            f"External Harness providers must declare a positive task limit or None: {provider.code!r}."
        )
    existing = _PROVIDERS.get(code)
    if existing is not None and existing is not provider:
        raise ValueError(f"Harness provider {code!r} is already registered.")
    _PROVIDERS[code] = provider


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True

    from .openai_provider import provider as openai_provider
    from modules import HARNESS_PROVIDER_MODULES, RETIRED_HARNESS_PROVIDER_MODULES

    register_provider(openai_provider)
    for module_name in (*HARNESS_PROVIDER_MODULES, *RETIRED_HARNESS_PROVIDER_MODULES):
        module = importlib.import_module(module_name)
        contribution = getattr(module, "provider", None)
        if contribution is None:
            raise RuntimeError(
                f"Harness provider contribution {module_name!r} does not expose 'provider'."
            )
        provider = cast(HarnessProvider, contribution)
        register_provider(provider)
        if module_name in RETIRED_HARNESS_PROVIDER_MODULES:
            _RETIRED_CODES.add(provider.code)


def get_provider(code: str) -> HarnessProvider:
    _load()
    normalized = code.strip().lower()
    try:
        return _PROVIDERS[normalized]
    except KeyError as exc:
        raise UnknownHarnessProviderError(normalized) from exc


def all_providers(*, include_retired: bool = False) -> tuple[HarnessProvider, ...]:
    """Return providers that may be selected, with explicit opt-in for upgrade reconciliation."""
    _load()
    return tuple(provider for code, provider in _PROVIDERS.items() if include_retired or code not in _RETIRED_CODES)


__all__ = [
    "UnknownHarnessProviderError",
    "all_providers",
    "get_provider",
    "register_provider",
]
