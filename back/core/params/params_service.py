"""
Synchronize and manage application parameters.

Usage:
    >>> from core.params import params_service
    >>> value = await params_service.get("param_name")
    >>> all_params = await params_service.get_all()
"""
from collections.abc import Awaitable, Callable
import hashlib
import json
from typing import Any, Dict, Optional, Sequence

from loguru import logger
from pydantic import ValidationError
from sqlalchemy import select

from core.database import get_db
from core.util import encrypt_value, get_encryption_service
from core.secrets import load_auth_secret_key
from .models import Param
from .consts import DEFAULT_PARAMS, INTERNAL_PARAMS, SECRET_PARAMS, Params
from .prompt_defaults import prompt_default
from .runtime_settings import RuntimeSettings, runtime_settings
from .web_push import load_web_push_keys

# In-memory parameter cache.
_params_cache: Dict[str, Optional[str]] = {}
_cache_loaded: bool = False
_change_listeners: list[Callable[[str, Optional[str]], Awaitable[None]]] = []


def is_secret(name: str) -> bool:
    """Return whether a parameter must never be exposed by the API."""
    return name in SECRET_PARAMS


def is_internal(name: str) -> bool:
    return name in INTERNAL_PARAMS


def is_prompt(name: str) -> bool:
    """Return whether a parameter follows the governed prompt lifecycle."""

    config = DEFAULT_PARAMS.get(name)
    return config is not None and config.get("kind") == "prompt"


def prompt_names() -> tuple[str, ...]:
    """Return every declared prompt parameter in stable order."""

    return tuple(sorted(name for name in DEFAULT_PARAMS if is_prompt(name)))


def prompt_default_digest(name: str) -> str:
    """Fingerprint the canonical English packaged default for a prompt."""

    config = DEFAULT_PARAMS.get(name)
    literal = config.get("value") if config is not None else None
    payload = json.dumps(
        {"name": name, "default": prompt_default(name) or literal or ""},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def register_change_listener(
    listener: Callable[[str, Optional[str]], Awaitable[None]],
) -> None:
    """Register an application callback invoked after a parameter is committed."""
    if listener not in _change_listeners:
        _change_listeners.append(listener)


def _serialize_runtime_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _validated_runtime_value(name: str, value: Optional[str]) -> tuple[Any, str] | None:
    """Validate and normalize a database-backed runtime field."""
    config = DEFAULT_PARAMS.get(name)
    if config is None:
        return None
    field_name = config.get("runtime_field")
    if not field_name:
        return None

    raw_value = value if value is not None else config.get("value")
    candidate_data = runtime_settings.model_dump()
    candidate_data[field_name] = raw_value
    candidate = RuntimeSettings.model_validate(candidate_data)
    typed_value = getattr(candidate, field_name)
    return typed_value, _serialize_runtime_value(typed_value)


def normalize(name: str, value: Optional[str]) -> Optional[str]:
    """Return the canonical persisted representation for a declared parameter."""
    config = DEFAULT_PARAMS.get(name)
    if config is None:
        return value
    if config.get("empty_uses_default") and (value is None or not value.strip()):
        return None

    normalized = _validated_runtime_value(name, value)
    if normalized is not None:
        _typed_value, serialized = normalized
        choices = config.get("choices")
        if choices and serialized not in choices:
            raise ValueError(
                f"{name} must be one of: {', '.join(choices)}"
            )
        return serialized
    return value


def _apply_runtime_setting(name: str, value: Optional[str]) -> None:
    normalized = _validated_runtime_value(name, value)
    if normalized is None:
        return
    config = DEFAULT_PARAMS[name]
    field_name = config.get("runtime_field")
    if not field_name:
        return
    typed_value, _ = normalized
    setattr(runtime_settings, field_name, typed_value)


async def _notify_change(name: str, value: Optional[str]) -> None:
    for listener in tuple(_change_listeners):
        try:
            await listener(name, value)
        except Exception:
            logger.exception("Parameter change listener failed for {}", name)


def _encrypt_for_storage(name: str, value: Optional[str]) -> Optional[str]:
    """Encrypt a secret parameter value, leaving ordinary values unchanged."""
    if value and name in SECRET_PARAMS:
        return encrypt_value(value)
    return value


def reveal(name: str, value: Optional[str]) -> Optional[str]:
    """Decrypt a secret parameter transparently.

    Plaintext legacy values remain supported.
    """
    if name in INTERNAL_PARAMS:
        if not value:
            raise ValueError("An internal secret is missing")
        # Internal credentials never accept plaintext or a different encryption key.
        return get_encryption_service().decrypt(value)
    if value and name in SECRET_PARAMS:
        enc = get_encryption_service()
        return enc.decrypt(value) if enc.is_encrypted(value) else value
    return value


async def _ensure_loaded() -> None:
    """Load parameters lazily when needed.

    Public getters call this helper automatically.
    """
    global _cache_loaded
    if not _cache_loaded:
        await load_params()


async def load_params() -> None:
    """Load all parameters from the database into memory."""
    global _params_cache, _cache_loaded
    result = await get_db().execute(select(Param))
    params = result.scalars().all()
    _params_cache = {param.name: reveal(param.name, param.value) for param in params}
    load_auth_secret_key(_params_cache.get(Params.AUTH_SECRET_KEY) or "")
    load_web_push_keys(_params_cache.get(Params.WEB_PUSH_VAPID_KEYS) or "")
    for name, value in _params_cache.items():
        try:
            _apply_runtime_setting(name, value)
        except (ValidationError, ValueError):
            logger.exception(
                "Ignoring invalid persisted runtime parameter {}; keeping current value",
                name,
            )
    _cache_loaded = True
    logger.info("Loaded {} parameters into memory", len(_params_cache))


async def get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Get a parameter value.

    Parameters are loaded from the database automatically when needed.

    Args:
        name: Parameter name.
        default: Fallback when the parameter does not exist.

    Returns:
        The parameter value or fallback.
    """
    await _ensure_loaded()
    return _params_cache.get(name, default)


async def get_or_default(name: str) -> Optional[str]:
    """Return a parameter value or its packaged/literal default.

    Resolution order is the database value, its canonical English packaged
    prompt, then the literal ``DEFAULT_PARAMS`` fallback.
    """
    value = await get(name)
    if value is not None:
        return value

    return await declared_default(name)


async def declared_default(name: str) -> Optional[str]:
    """Return a canonical English prompt default, then its literal declaration."""

    packaged = prompt_default(name)
    if packaged is not None:
        return packaged

    config = DEFAULT_PARAMS.get(name)
    return config.get("value") if config else None


async def value_for_display(name: str, value: Optional[str]) -> Optional[str]:
    """Expose an effective default only for parameters that explicitly request it."""

    config = DEFAULT_PARAMS.get(name)
    if value is not None or not config or not config.get("display_default"):
        return value
    return await declared_default(name)


async def has(name: str) -> bool:
    """Check whether a parameter exists.

    Parameters are loaded from the database automatically when needed.

    Args:
        name: Parameter name.

    Returns:
        Whether the parameter exists.
    """
    await _ensure_loaded()
    return name in _params_cache


async def get_all() -> Dict[str, Optional[str]]:
    """Return all parameters as a dictionary.

    Parameters are loaded from the database automatically when needed.

    Returns:
        A copy of the parameter dictionary.
    """
    await _ensure_loaded()
    return _params_cache.copy()


async def set(name: str, value: Optional[str]) -> bool:
    """Update an existing parameter value.

    Args:
        name: Parameter name.
        value: New value.

    Returns:
        Whether the update succeeded; false means the parameter does not exist.
    """
    if is_internal(name):
        raise ValueError("Internal parameters cannot be changed")
    if not await has(name):
        logger.warning("Attempted to update nonexistent parameter {}", name)
        return False

    normalized_value = normalize(name, value)
    if is_prompt(name) and normalized_value == await declared_default(name):
        normalized_value = None
    db = get_db()

    result = await db.execute(select(Param).where(Param.name == name))
    param = result.scalar_one()

    # The database stores encrypted secrets while the cache retains plaintext.
    param.value = _encrypt_for_storage(name, normalized_value)
    if is_prompt(name):
        # Saving, resetting, or explicitly keeping a prompt acknowledges the
        # packaged default currently presented to the administrator.
        param.default_digest = prompt_default_digest(name)

    await db.commit()
    await db.refresh(param)

    if _cache_loaded:
        _params_cache[name] = normalized_value

    _apply_runtime_setting(name, normalized_value)
    await _notify_change(name, normalized_value)

    return True


async def refresh() -> None:
    """Reload every parameter from the database.

    This forces the in-memory cache to synchronize with persistent values.
    """
    global _cache_loaded
    _cache_loaded = False
    await load_params()


async def set_runtime_values(values: dict[str, str]) -> None:
    """Commit a coherent group of runtime preferences before publishing to readers."""
    await _ensure_loaded()
    normalized: dict[str, Optional[str]] = {}
    for name, value in values.items():
        config = DEFAULT_PARAMS.get(name)
        if is_internal(name) or config is None or not config.get("runtime_field"):
            raise ValueError("Only administrable runtime parameters can be grouped")
        normalized[name] = normalize(name, value)
    db = get_db()
    rows = list(await db.scalars(select(Param).where(Param.name.in_(normalized))))
    if len(rows) != len(normalized):
        raise ValueError("Runtime parameters have not been initialized")
    for row in rows:
        row.value = _encrypt_for_storage(row.name, normalized[row.name])
    await db.commit()
    # No awaits while switching the in-process view of a configuration group.
    for name, value in normalized.items():
        _params_cache[name] = value
        _apply_runtime_setting(name, value)
    for name, value in normalized.items():
        await _notify_change(name, value)


def declared_rows() -> tuple[dict[str, object], ...]:
    """Compile declared parameters into rows while preserving runtime values on merge."""

    rows: list[dict[str, object]] = []
    for name in sorted(DEFAULT_PARAMS):
        initial_value = DEFAULT_PARAMS[name].get("value")
        normalized = normalize(name, initial_value)
        rows.append(
            {
                "name": name,
                "value": _encrypt_for_storage(name, normalized),
            }
        )
    return tuple(rows)


async def sync() -> None:
    """Apply the module DataSource through the DbAdmin merge engine."""
    from core.dbadmin import reconcile_dataset
    from .dbadmin import datasets

    db = get_db()
    result = await reconcile_dataset(db, datasets()[0])
    await db.commit()
    logger.info(
        "Parameter dataset synchronized: {} inserted, {} removed",
        result.inserted,
        result.removed,
    )


async def get_all_with_metadata() -> Sequence[Param]:
    """Return all parameter names and values sorted by name."""
    result = await get_db().execute(select(Param).order_by(Param.name))
    return result.scalars().all()
