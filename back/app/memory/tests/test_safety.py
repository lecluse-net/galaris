import pytest

from app.memory.safety import assert_safe_text, assert_safe_value, redact_secrets


@pytest.mark.parametrize("text", [
    "Voici un secret : les fleurs changent de couleur.",
    "The garden has a secret: flowers open at midnight.",
    "<p>Un secret : chaque fleur cache une étoile.</p>",
])
def test_prose_is_preserved_by_direct_writes_and_automatic_capture(text):
    assert_safe_text(text)
    assert redact_secrets(text) == text


@pytest.mark.parametrize("text", [
    "secret: synthetic-credential",
    "  SECRET : synthetic-credential",
    "\u00a0secret : synthetic-credential",
    "- secret : synthetic-credential",
    "Settings\nsecret : synthetic-credential",
    "<p>secret : synthetic-credential</p>",
    "{secret: synthetic-credential}",
    "Settings; secret: synthetic-credential",
    "Settings: secret: synthetic-credential",
    "Inline secret=synthetic-credential",
    "Inline password : synthetic-credential",
    "Inline token=synthetic-credential",
    "api_key: synthetic-credential",
    "Bearer synthetic-credential",
    "-----BEGIN PRIVATE KEY-----",
])
def test_credential_assignments_remain_blocked_and_redacted(text):
    with pytest.raises(ValueError, match="credential-like"):
        assert_safe_text(text)
    redacted = redact_secrets(text)
    assert redacted is None or "synthetic-credential" not in redacted


def test_structured_secret_fields_remain_blocked():
    with pytest.raises(ValueError, match="metadata contains credential-like"):
        assert_safe_value({"nested": [{"secret": "synthetic-credential"}]})
    assert_safe_value({"secret": "[redacted]"})


@pytest.mark.parametrize("placeholder", ["[redacted]", "<redacted>", "***", "xxxxx", "example"])
def test_redaction_remains_idempotent_for_supported_placeholders(placeholder):
    text = f"secret: {placeholder}"
    assert_safe_text(text)
    assert redact_secrets(text) == text


def test_credential_rejection_explains_the_cause_without_echoing_content():
    from app.tools.tool_errors import classify_tool_failure

    with pytest.raises(ValueError) as error:
        assert_safe_text("secret: synthetic-credential")
    failure = classify_tool_failure(error.value)
    assert failure.kind == "actionable"
    assert "credential-like" in failure.detail
    assert "synthetic-credential" not in failure.detail
