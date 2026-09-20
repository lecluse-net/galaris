"""Internal credentials fail closed instead of falling back to environment values."""

import pytest

from core import secrets


@pytest.mark.parametrize("invalid", ["", "short", " " * 40])
def test_invalid_signing_key_cannot_enable_authentication_or_replace_a_loaded_key(monkeypatch, invalid):
    monkeypatch.setattr(secrets, "_auth_secret_key", None)
    monkeypatch.setenv("AUTH_SECRET_KEY", "environment-key-must-not-be-used-0001")
    with pytest.raises(RuntimeError, match="have not been loaded"):
        secrets.auth_secret_key()
    with pytest.raises(ValueError, match="missing or invalid"):
        secrets.load_auth_secret_key(invalid)
    with pytest.raises(RuntimeError, match="have not been loaded"):
        secrets.auth_secret_key()

    expected = "persistent-signing-key-kept-intact-0001"
    secrets.load_auth_secret_key(expected)
    with pytest.raises(ValueError, match="missing or invalid"):
        secrets.load_auth_secret_key(invalid)
    assert secrets.auth_secret_key() == expected


@pytest.mark.parametrize("contents", [None, "short", " " * 40, "shared-browser-credential-0000000001\n"])
def test_browser_requires_the_shared_credential_file_without_environment_fallback(tmp_path, monkeypatch, contents):
    path = tmp_path / "browser-token"
    monkeypatch.setattr(secrets, "BROWSER_TOKEN_PATH", path)
    monkeypatch.setenv("BROWSER_EXECUTOR_TOKEN", "environment-token-must-not-be-used-0001")
    if contents is not None:
        path.write_text(contents)
    if contents is None:
        with pytest.raises(RuntimeError, match="unavailable"):
            secrets.browser_executor_token()
    elif len(contents.strip()) < 32:
        with pytest.raises(RuntimeError, match="invalid"):
            secrets.browser_executor_token()
    else:
        assert secrets.browser_executor_token() == contents.strip()
