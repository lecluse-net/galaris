"""Process-local signing key and the dedicated browser credential file.

The signing key is hydrated from encrypted Params before serving requests.
The encryption master key remains exclusively in the deployment settings.
"""

from pathlib import Path


BROWSER_TOKEN_PATH = Path("/run/galaris-browser/token")
_auth_secret_key: str | None = None


def load_auth_secret_key(value: str) -> None:
    """Install the persistent signing key; never invent a process-local fallback."""
    if len(value.strip()) < 32:
        raise ValueError("The internal authentication signing key is missing or invalid")
    global _auth_secret_key
    _auth_secret_key = value


def auth_secret_key() -> str:
    """Return the key loaded at startup, failing closed before hydration."""
    if _auth_secret_key is None:
        raise RuntimeError("Internal authentication secrets have not been loaded")
    return _auth_secret_key


def browser_executor_token() -> str:
    """Read the credential shared with the browser, without environment fallback."""
    try:
        value = BROWSER_TOKEN_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        raise RuntimeError("The shared browser credential is unavailable") from None
    if len(value) < 32:
        raise RuntimeError("The shared browser credential is invalid")
    return value
