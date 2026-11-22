"""Reviewers see the frozen action, without transport internals or active markup."""

import pytest

from app.services.authorization_presentation import notification_content, present_action


@pytest.mark.parametrize("language,title,to_label", [("fr", "Envoyer un e-mail", "Destinataires"),
                                                   ("en", "Send an email", "Recipients")])
def test_mail_review_uses_frozen_recipients_content_and_attachments(language, title, to_label):
    arguments = {"to": ["original@example.test"], "subject": "Original draft", "body": "Old text",
                 "idempotency_key": "synthetic-key", "prepared": {
                     "to": ["recipient@example.test"], "cc": ["copy@example.test"], "bcc": ["hidden@example.test"],
                     "subject": "Synthetic greeting", "body": "Hello,\n\nHave a good day.",
                     "attachments": [{"filename": "greeting.txt", "sha256": "synthetic-hash", "size": 42}],
                     "delivery_id": "synthetic-delivery", "mime_sha256": "synthetic-mime"}}
    presentation = present_action(name="mail_send", source="domain", arguments=arguments, language=language)
    assert presentation["title"] == title
    assert presentation["fields"][0] == {"label": to_label, "value": "recipient@example.test"}
    body, body_html = notification_content(presentation, language=language)
    assert body_html is not None and to_label in body_html
    for expected in ("copy@example.test", "hidden@example.test", "Synthetic greeting", "Have a good day.", "greeting.txt"):
        assert expected in body and expected in body_html
    for technical in ("Original draft", "Old text", "original@example.test", "synthetic-key", "synthetic-delivery", "synthetic-mime", "synthetic-hash"):
        assert technical not in body and technical not in body_html
    assert arguments["subject"] == "Original draft"


def test_generic_review_retains_nested_parameters_false_and_zero_and_redacts_secrets():
    presentation = present_action(name="external_action", source="mcp", arguments={
        "custom_options": {"enabled": False, "limit": 0}, "token": "synthetic-secret",
        "url": "https://example.test/path?token=synthetic-url-secret", "empty": None,
    }, language="en")
    fields = {field["label"]: field["value"] for field in presentation["fields"]}
    assert fields["Custom options"] == "enabled: No\nlimit: 0"
    assert fields["Web address"] == "https://example.test/path"
    assert fields["Token"] == "[redacted]"
    assert "Empty" not in fields
    assert "synthetic-secret" not in str(presentation)


def test_markup_is_inert_and_shortened_notifications_are_explicit():
    presentation = present_action(name="external_action", source="mcp", arguments={
        "content": '<img src="https://example.test/track">\n[Approve](https://example.test)\n```html\n<script>alert(1)</script>\n```',
    }, language="en")
    body, body_html = notification_content(presentation, language="en")
    assert body_html is not None
    assert "&lt;img" in body_html and "&lt;script&gt;" in body_html
    assert "<img" not in body_html and "<script" not in body_html and "<a " not in body_html
    assert "<img" not in body and "<script" not in body and "[Approve](" not in body and "```" not in body
    presentation["fields"][0]["value"] = "x" * 7000
    shortened, body_html = notification_content(presentation, language="en")
    assert "Shortened preview" in shortened
    assert body_html is None
    assert len(presentation["fields"][0]["value"]) == 7000


def test_goal_notification_keeps_editorial_structure_and_a_readable_text_fallback():
    presentation = present_action(name="goal_create", source="mcp", language="fr", html_field="description", arguments={
        "title": "Bilan <2026>", "description": "<h2>Étapes</h2><ol><li>Relire le <strong>bilan</strong></li></ol>",
    })
    body, body_html = notification_content(presentation, language="fr", scope="Portée de la décision.")
    assert "Relire le bilan" in body and "<h2>" not in body
    assert body_html is not None and "<strong>bilan</strong>" in body_html
    assert "Bilan &lt;2026&gt;" in body_html and "Portée de la décision." in body_html
    presentation["fields"][1]["value"] = "<p>" + "x" * 7000 + "</p>"
    shortened, body_html = notification_content(presentation, language="fr")
    assert "Aperçu abrégé" in shortened and body_html is None


def test_invalid_goal_markup_stays_literal_in_the_notification():
    presentation = present_action(name="goal_update", source="mcp", language="en", html_field="description", arguments={
        "description": "<script>synthetic review script</script><p>Proposed description</p>",
    })
    body, body_html = notification_content(presentation, language="en")
    assert "&lt;script&gt;" in body
    assert body_html is not None and "&lt;script&gt;" in body_html
    assert "<script" not in body_html


def test_codex_review_explains_the_real_command_without_showing_the_transport_envelope():
    presentation = present_action(
        name="item/commandExecution/requestApproval", source="runtime", runtime="codex", language="fr",
        arguments={"request": {"cwd": "/synthetic"}, "item": {"command": "echo synthetic", "status": "waiting"}},
    )
    assert presentation["title"] == "Exécuter une commande avec Codex"
    assert presentation["fields"] == [
        {"label": "Commande", "value": "echo synthetic"},
        {"label": "Dossier de travail", "value": "/synthetic"},
    ]
