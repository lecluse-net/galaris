"""Human-readable projections of an approval's immutable, redacted arguments."""

import re
from html import escape
from typing import Literal, NotRequired, TypedDict, cast

from core.i18n import render_prompt, t
from core.util import RichTextError, normalize_html, visible_text

from .authorization import redacted_action_arguments
from .authorization_models import ActionAuthorization
from .mcp_loader import native_service_codes_for_service
from .schemas import Service
from .service import get_service_by_id


_GOAL_HTML_FIELDS = {
    "goal_create": "description",
    "goal_update": "description",
    "goal_update_suivi": "tracking_content",
}
_NOTIFICATION_LIMIT = 6000
_NATIVE_ACTIONS = {
    "goal_management": {
        "goal_create",
        "goal_update",
        "goal_pause",
        "goal_resume",
        "goal_complete",
        "goal_delete",
    },
    "galaris": {
        "goal_update_suivi",
        "goal_run_now",
        "task_run",
        "task_stop",
        "process_start",
        "process_create",
        "process_update",
        "process_share",
        "process_run_cancel",
    },
    "file_sharing": {
        "file_create",
        "file_write",
        "file_edit",
        "file_append",
        "file_copy",
        "file_move",
        "file_rename",
        "file_delete",
        "file_to_pdf",
    },
    "calendar": {
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
        "calendar_action_set",
    },
    "messenger": {
        "messenger_room_send_message",
        "messenger_send_message_to_user",
        "messenger_send_audio_message",
        "messenger_send_file_to_user",
        "messenger_room_send_file",
    },
    "topic": {
        "topic_create",
        "topic_update",
        "topic_item_move",
        "topic_merge",
        "topic_split",
    },
}
_FIELD_LABELS = {
    "to", "cc", "bcc", "subject", "body", "html_body", "reply_to", "attachments",
    "command", "cwd", "path", "url", "content", "destination", "source", "sender",
    "title",
    "name",
    "goal_id",
    "referrer_display_name",
    "referrer_connection_id",
    "referrer_user_id",
    "expected_revision",
    "cycle_delay_seconds",
    "referrer_max_reminders",
    "schedule_enabled",
    "schedule",
    "uri",
    "message",
    "room_id",
    "recipient",
    "calendar_id",
    "event_id",
    "task_id",
    "process_code",
    "workflow_id",
    "run_id",
    "changes",
}
_GOAL_FIELD_LABELS = {"agent_id", "active", "weekdays", "start_time", "end_time"}
_EXPLANATIONS = {
    "goal_create": "goal_create_explanation",
    "goal_update": "goal_update_explanation",
    "goal_update_suivi": "goal_tracking_explanation",
}
_RUNTIME_LABELS = {
    "hermes": "Hermès", "codex": "Codex", "claude_agent": "Claude Agent",
    "deepseek_harness": "DeepSeek Harness", "openai_messages": "OpenAI Messages",
}
_RUNTIME_ACTIONS = {
    "command": "runtime_command", "terminal": "runtime_command", "shell": "runtime_command", "bash": "runtime_command",
    "item/commandexecution/requestapproval": "runtime_command",
    "write_file": "runtime_files", "edit_file": "runtime_files", "write": "runtime_files",
    "edit": "runtime_files", "apply_patch": "runtime_files", "item/filechange/requestapproval": "runtime_files",
    "read_file": "runtime_read", "read": "runtime_read",
}


class ApprovalField(TypedDict):
    label: str
    value: str
    format: NotRequired[Literal["html"]]


class ApprovalPresentation(TypedDict):
    title: str
    fields: list[ApprovalField]
    explanation: NotRequired[str]


def runtime_label(runtime: str, language: str) -> str:
    return _RUNTIME_LABELS.get(runtime) or t("approval_preview.runtime_generic", language)


def _native_action(name: str, source: str, kind: str, service: Service | None) -> bool:
    return (
        source == "mcp" and kind == "tool" and service is not None
        and any(name in _NATIVE_ACTIONS.get(code, ()) for code in native_service_codes_for_service(service))
    )


def _title(
    *, name: str, source: str, kind: str, language: str, native: bool,
    service: Service | None, runtime: str,
) -> str:
    if source == "domain" and name in {"mail_send", "mail_reply", "mail_forward"}:
        return t("approval_preview.send_mail", language)
    if source == "mcp" and kind == "tool" and name == "mail_process":
        return t("approval_preview.process_mail", language)
    if native:
        return t(f"approval_preview.actions.{name}", language)
    if source == "runtime":
        key = _RUNTIME_ACTIONS.get(name.casefold(), "runtime_other")
        return render_prompt(t(f"approval_preview.{key}", language),
                             function=name, runtime=runtime_label(runtime, language))
    if source == "mcp":
        key = {"resource": "external_resource", "prompt": "external_prompt"}.get(kind, "external_tool")
        service_label = f"« {service.label} »" if service else t("approval_preview.unknown_service", language)
        return render_prompt(t(f"approval_preview.{key}", language), function=name, service=service_label)
    return t("approval_preview.unknown_action", language)


def approval_title(row: ActionAuthorization, language: str, service: Service | None) -> str:
    return _title(
        name=row.capability_name, source=row.source, kind=row.capability_kind, language=language,
        native=_native_action(row.capability_name, row.source, row.capability_kind, service),
        service=service, runtime=row.runtime,
    )


def approval_scope(row: ActionAuthorization, *, language: str, can_remember: bool) -> str:
    if not can_remember:
        return t("approval_preview.once", language)
    if row.source == "runtime":
        return render_prompt(t("permissions.runtime_scope", language), runtime=runtime_label(row.runtime, language))
    return t("permissions.function_scope", language)


def matching_approval_names(needle: str, language: str) -> set[str]:
    names = {name for actions in _NATIVE_ACTIONS.values() for name in actions
             if needle in t(f"approval_preview.actions.{name}", language).lower()}
    names.update(name for name, key in _RUNTIME_ACTIONS.items()
                 if needle in t(f"approval_preview.{key}", language).lower())
    return names


def _value(value: object, language: str, *, goal: bool = False) -> str:
    if isinstance(value, dict):
        entries: list[str] = []
        for key, item in cast(dict[str, object], value).items():
            label = t(f"approval_preview.{key}", language) if goal and key in _GOAL_FIELD_LABELS else key.replace("_", " ")
            text = _value(item, language, goal=goal)
            if goal and key == "weekdays" and isinstance(item, list):
                days = cast(list[object], item)
                text = ", ".join(t(f"approval_preview.days.{day}", language)
                                 if type(day) is int and 0 <= day <= 6 else str(day) for day in days)
            entries.append(f"{label}: {text}")
        return "\n".join(entries)
    if isinstance(value, list):
        return "\n".join(_value(item, language, goal=goal) for item in cast(list[object], value))
    if isinstance(value, bool):
        return t("approval_preview.yes" if value else "approval_preview.no", language)
    return str(value) if value is not None else "—"


async def present_authorization(
    row: ActionAuthorization, *, arguments: dict[str, object], language: str, service: Service | None = None,
) -> ApprovalPresentation:
    if service is None and row.service_id is not None:
        service = await get_service_by_id(row.service_id)
    native = _native_action(row.capability_name, row.source, row.capability_kind, service)
    return present_action(
        name=row.capability_name, source=row.source, arguments=arguments, language=language,
        kind=row.capability_kind, service=service, runtime=row.runtime, native=native,
        html_field=_GOAL_HTML_FIELDS.get(row.capability_name) if native else None,
    )


def _codex_review_values(name: str, arguments: dict[str, object]) -> dict[str, object]:
    if name == "item/commandExecution/requestApproval":
        request, item = arguments.get("request"), arguments.get("item")
        if isinstance(request, dict) and isinstance(item, dict):
            parameters = cast(dict[str, object], request)
            operation = cast(dict[str, object], item)
            command = parameters.get("command") or operation.get("command")
            if command:
                return {"command": command, "cwd": parameters.get("cwd") or operation.get("cwd")}
    if name == "item/fileChange/requestApproval" and isinstance(item := arguments.get("item"), dict):
        if changes := cast(dict[str, object], item).get("changes"):
            return {"changes": changes}
    return arguments


def present_action(
    *, name: str, source: str, arguments: dict[str, object], language: str, html_field: str | None = None,
    kind: str = "tool", service: Service | None = None, runtime: str = "", native: bool = False,
) -> ApprovalPresentation:
    arguments = cast(dict[str, object], redacted_action_arguments(arguments))
    fields: list[ApprovalField] = []
    mail = source == "domain" and name in {"mail_send", "mail_reply", "mail_forward"}
    title = _title(name=name, source=source, kind=kind, language=language, native=native, service=service, runtime=runtime)
    if name == "mail_process" and source == "mcp" and kind == "tool":
        arguments = {key: value for key, value in arguments.items() if key != "message_ref"}
    if mail and isinstance(arguments.get("prepared"), dict):
        # The frozen delivery is what will be sent, even when original inputs differ.
        snapshot = cast(dict[str, object], arguments["prepared"])
        values = {key: snapshot.get(key) for key in ("to", "cc", "bcc", "subject", "body", "html_body", "attachments")}
        values["reply_to"] = arguments.get("reply_to")
    else:
        values = _codex_review_values(name, arguments) if source == "runtime" and runtime == "codex" else arguments
    goal = native and name.startswith("goal_")
    for key, value in values.items():
        if value is None or value == "" or value == [] or value == {} or (goal and key == "expected_revision"):
            continue
        label = key.replace("_", " ").capitalize()
        if key == html_field or key in _FIELD_LABELS or (goal and key in _GOAL_FIELD_LABELS):
            label = t(f"approval_preview.{key}", language)
        if mail and key == "attachments" and isinstance(value, list):
            value = [cast(dict[str, object], item).get("filename", cast(dict[str, object], item)) if isinstance(item, dict) else item
                     for item in cast(list[object], value)]
        if key == html_field and isinstance(value, str):
            try:
                html = normalize_html(value, limit_length=key != "tracking_content")
            except RichTextError:
                html = ""
            if html:
                fields.append({"label": label, "value": html, "format": "html"})
                continue
        fields.append({"label": label, "value": _value(value, language, goal=goal)})
    presentation: ApprovalPresentation = {"title": title, "fields": fields}
    if (native or html_field is not None) and (explanation := _EXPLANATIONS.get(name)):
        presentation["explanation"] = t(f"approval_preview.{explanation}", language)
    return presentation


def _escape_markdown(value: str) -> str:
    # Treat every value in the text notification as literal.
    return re.sub(r"([\\`*_\[\]#|~])", r"\\\1", escape(value, quote=False))


def notification_content(
    presentation: ApprovalPresentation, *, language: str, scope: str = "",
) -> tuple[str, str | None]:
    title, fields = presentation["title"], presentation["fields"]
    text_parts = [_escape_markdown(title)]
    rich_content = any(field.get("format") == "html" for field in fields)
    html_parts = [f"<p>{escape(title)}</p>"] if rich_content else []
    if explanation := presentation.get("explanation"):
        text_parts.append(_escape_markdown(explanation))
        if rich_content:
            html_parts.append(f"<p>{escape(explanation)}</p>")
    for field in fields:
        label, value = field["label"], field["value"]
        is_html = field.get("format") == "html"
        text = visible_text(value) if is_html else value
        text_parts.append(f"{_escape_markdown(label)} :\n{_escape_markdown(text)}")
        if rich_content:
            html = value if is_html else "<p>" + escape(value).replace("\n", "<br>") + "</p>"
            html_parts.extend((f"<p><strong>{escape(label)}</strong></p>", html))
    body = "\n\n".join(text_parts)
    if len(body) > _NOTIFICATION_LIMIT:
        body = body[:_NOTIFICATION_LIMIT] + "\n\n" + t("approval_preview.truncated", language)
        rich_content = False
    decision_scope = scope or t("approval_preview.once", language)
    body += "\n\n" + decision_scope
    if not rich_content:
        return body, None
    html_parts.append(f"<p>{escape(decision_scope)}</p>")
    body_html = "".join(html_parts)
    return body, body_html if len(body_html) <= _NOTIFICATION_LIMIT else None
