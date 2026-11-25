"""Human-readable projections of an approval's immutable, redacted arguments."""

import re
from html import escape
from typing import Literal, NotRequired, TypedDict, cast
from uuid import UUID

from app.agent import management_scope_for
from core.database import get_db
from core.i18n import render_prompt, t
from core.user import get_user_record
from core.util import RichTextError, normalize_html, parse_resource_uri, visible_text

from .authorization import redacted_action_arguments
from .authorization_models import ActionAuthorization
from .mcp_loader import native_service_codes_for_service
from .schemas import Service
from .service import get_service_by_id


_NATIVE_HTML_FIELDS = {
    "goal_create": "description",
    "goal_update": "description",
    "goal_update_suivi": "tracking_content",
    "task_run": "objective",
}
_AGENT_ARGUMENTS = {"agent_create": "configuration", "agent_update": "changes"}
_AGENT_HTML_FIELDS = {"job_description", "personality"}
_AGENT_FIELD_LABELS = {
    "agent_driver", "code", "fallback_profile_id", "first_name", "job_description", "job_title",
    "last_name", "personality", "profile_id", "team_ids", "title_id", "user_id", "voice",
}
_NOTIFICATION_LIMIT = 6000
_MOVED_GOAL_ACTIONS = {"goal_update_suivi", "goal_run_now"}
_MOVED_PROCESS_ACTIONS = {"process_start", "process_create", "process_update", "process_share", "process_run_cancel"}
_NATIVE_ACTIONS = {
    "agent": {*_AGENT_ARGUMENTS, "agent_delete"},
    "goal": {
        *_MOVED_GOAL_ACTIONS,
        "goal_create",
        "goal_update",
        "goal_pause",
        "goal_resume",
        "goal_complete",
        "goal_delete",
    },
    "galaris": {
        # Keep the human-readable presentation of approvals recorded before the split.
        *_MOVED_GOAL_ACTIONS,
        *_MOVED_PROCESS_ACTIONS,
        "task_run",
        "task_stop",
    },
    "process": _MOVED_PROCESS_ACTIONS,
    "task": {"task_run", "task_stop", "task_stop_conversation", "task_cancel"},
    "document": {"document_share"},
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
    "service_code",
    "account_email",
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
    "document_id",
    "topic_id",
    "source_topic_id",
    "target_topic_id",
    "contact_id",
    "target_agent_id",
    "uid",
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
_RESOURCE_FIELDS = {
    "goal_id": "galaris://goal/",
    "task_id": "galaris://task/",
    "document_id": "document://",
    "topic_id": "galaris://topic/",
    "source_topic_id": "galaris://topic/",
    "target_topic_id": "galaris://topic/",
    "run_id": "galaris://processes/runs/",
    "room_id": "galaris://room/",
    "contact_id": "galaris://contact/",
    "calendar_id": "galaris://calendar/",
    "agent_id": "galaris://agent/",
    "target_agent_id": "galaris://agent/",
    "process_code": "galaris://processes/",
    "workflow_id": "galaris://process/",
}
_URI_FIELDS = {"uri", "path", "source", "destination", "file_uri", "resource_uri"}
_UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", re.IGNORECASE)


class ApprovalField(TypedDict):
    label: str
    value: str
    format: NotRequired[Literal["html"]]
    resource_uri: NotRequired[str]


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
    if isinstance(value, str) and (_UUID.fullmatch(value) or (
        value.startswith(("galaris://", "document://", "data://", "memory://", "file://")) and _UUID.search(value)
    )):
        return t("approval_preview.unavailable_resource", language)
    return str(value) if value is not None else "—"


def _review_uri(key: str, value: object) -> str | None:
    if not isinstance(value, (str, int)) or isinstance(value, bool) or len(str(value)) > 2048:
        return None
    text = str(value).strip()
    prefix = _RESOURCE_FIELDS.get(key)
    if prefix is None and key not in _URI_FIELDS:
        return None
    if "://" not in text:
        if prefix is None:
            return None
        if prefix in {"galaris://agent/", "galaris://calendar/"}:
            if not text.isascii() or not text.isdecimal() or not 0 < int(text) <= 2_147_483_647:
                return None
        elif key in {"workflow_id", "process_code"}:
            if not re.fullmatch(r"[\w.-]{1,255}", text, re.ASCII):
                return None
        else:
            try:
                text = str(UUID(text))
            except ValueError:
                return None
        text = prefix + text
    try:
        reference = parse_resource_uri(text)
    except ValueError:
        return None
    prefixes = ("galaris://process/", "galaris://processes/") if key == "workflow_id" else (prefix,) if prefix else ()
    if reference.is_collection or (prefixes and not reference.uri.startswith(prefixes)):
        return None
    if reference.scheme in {"document", "data", "file"} and len(reference.segments) == 1:
        identity = reference.segments[0]
    elif reference.scheme == "galaris":
        segments = reference.segments
        if len(segments) == 2 and segments[0] in {"agent", "calendar"}:
            identifier = segments[1]
            if identifier.isascii() and identifier.isdecimal() and 0 < int(identifier) <= 2_147_483_647:
                return f"galaris://{segments[0]}/{int(identifier)}"
            return None
        if len(segments) == 2 and segments[0] in {"process", "processes"} and len(segments[1]) <= 255:
            return reference.uri
        if len(segments) == 2 and segments[0] in {"goal", "task", "topic", "room", "contact"}:
            identity = segments[1]
        elif len(segments) == 3 and segments[:2] == ("processes", "runs"):
            identity = segments[2]
        else:
            return None
    else:
        return None
    if not _UUID.fullmatch(identity):
        return None
    return f"{reference.uri.rsplit('/', 1)[0]}/{identity.lower()}"


async def present_authorization(
    row: ActionAuthorization, *, arguments: dict[str, object], language: str, service: Service | None = None,
) -> ApprovalPresentation:
    if service is None and row.service_id is not None:
        service = await get_service_by_id(row.service_id)
    references: dict[str, tuple[str, str | None]] = {}
    if _native_action(row.capability_name, row.source, row.capability_kind, service):
        from app.file_share import review_calendar_event_label, review_resource

        candidates = {key: uri for key, value in arguments.items() if (uri := _review_uri(key, value))}
        if row.capability_name == "topic_item_move":
            item_type = arguments.get("item_type")
            if isinstance(item_type, str) and item_type in {"document", "task"}:
                if item := _review_uri(f"{item_type}_id", arguments.get("item_id")):
                    candidates["item_id"] = item
        if candidates and (reviewer := await get_user_record(row.approver_user_id)):
            scope = await management_scope_for(reviewer, get_db())
            for key, uri in candidates.items():
                detail = await review_resource(uri, agent_id=row.agent_id, reviewer=reviewer, scope=scope)
                if detail is not None and not _UUID.fullmatch(detail[0]):
                    references[key] = detail
            if row.capability_name in {"calendar_update_event", "calendar_delete_event", "calendar_action_set"}:
                calendar_id, uid = arguments.get("calendar_id"), arguments.get("uid")
                if "calendar_id" in candidates and type(calendar_id) is int and isinstance(uid, str) and 0 < len(uid) <= 255:
                    title = await review_calendar_event_label(calendar_id, uid, reviewer=reviewer, scope=scope)
                    if title and not _UUID.fullmatch(title):
                        references["uid"] = (title, None)
    return present_action(
        name=row.capability_name, source=row.source, arguments=arguments, language=language,
        kind=row.capability_kind, service=service, runtime=row.runtime, references=references,
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
    kind: str = "tool", service: Service | None = None, runtime: str = "",
    references: dict[str, tuple[str, str | None]] | None = None,
) -> ApprovalPresentation:
    arguments = cast(dict[str, object], redacted_action_arguments(arguments))
    fields: list[ApprovalField] = []
    native = _native_action(name, source, kind, service)
    agent_profile = native and name in _AGENT_ARGUMENTS
    html_fields = {html_field} if html_field else set[str]()
    if native and (native_html_field := _NATIVE_HTML_FIELDS.get(name)):
        html_fields.add(native_html_field)
    if agent_profile:
        html_fields.update(_AGENT_HTML_FIELDS)
        envelope = _AGENT_ARGUMENTS[name]
        if isinstance(profile := arguments.get(envelope), dict):
            arguments = {key: value for key, value in arguments.items() if key != envelope}
            arguments.update(cast(dict[str, object], profile))
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
        empty = value is None or value == "" or value == [] or value == {}
        show_empty = agent_profile and name == "agent_update" and key in _AGENT_FIELD_LABELS
        if (empty and not show_empty) or (goal and key == "expected_revision"):
            continue
        label = key.replace("_", " ").capitalize()
        if native and name in _NATIVE_ACTIONS["agent"] and key == "agent_id":
            label = t("approval_preview.target_agent_id", language)
        elif key in html_fields or key in _FIELD_LABELS or (goal and key in _GOAL_FIELD_LABELS) or (agent_profile and key in _AGENT_FIELD_LABELS):
            label = t(f"approval_preview.{key}", language)
        elif native and key in {"resource_uri", "file_uri"}:
            label = t("approval_preview.uri", language)
        if references and (reference := references.get(key)):
            title, uri = reference
            field: ApprovalField = {"label": label, "value": title}
            if uri:
                field["resource_uri"] = uri
            fields.append(field)
            continue
        if empty:
            # Validated models can contribute defaults to the frozen payload.
            fields.append({"label": label, "value": "—" if value is None else repr(value)})
            continue
        if mail and key == "attachments" and isinstance(value, list):
            value = [cast(dict[str, object], item).get("filename", cast(dict[str, object], item)) if isinstance(item, dict) else item
                     for item in cast(list[object], value)]
        if key in html_fields and isinstance(value, str):
            try:
                html = normalize_html(value, limit_length=key != "tracking_content")
            except RichTextError:
                html = ""
            if html:
                fields.append({"label": label, "value": html, "format": "html"})
                continue
        unavailable = native and (_review_uri(key, value) is not None or key in {"uid", "room_id"})
        fields.append({"label": label, "value": t("approval_preview.unavailable_resource", language)
                       if unavailable else _value(value, language, goal=goal)})
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
    explanation = presentation.get("explanation")
    if explanation:
        text_parts.append(_escape_markdown(explanation))
    for field in fields:
        value = field["value"]
        text = visible_text(value) if field.get("format") == "html" else value
        text_parts.append(f"{_escape_markdown(field['label'])} :\n{_escape_markdown(text)}")
    decision_scope = scope or t("approval_preview.once", language)
    body = "\n\n".join(text_parts)
    if len(body) > _NOTIFICATION_LIMIT:
        body = body[:_NOTIFICATION_LIMIT] + "\n\n" + t("approval_preview.truncated", language)
        return body + "\n\n" + decision_scope, None
    body += "\n\n" + decision_scope

    html_parts = [f"<h3>{escape(title)}</h3>"]
    if explanation:
        html_parts.append(f"<p>{escape(explanation)}</p>")
    rows: list[str] = []
    sections: list[str] = []
    for field in fields:
        label, value = escape(field["label"]), field["value"]
        if field.get("format") == "html":
            sections.append(f"<p><strong>{label}</strong></p>{value}")
        elif uri := field.get("resource_uri"):
            rows.append(f'<tr><th>{label}</th><td><a href="{escape(uri)}">{escape(value)}</a></td></tr>')
        elif "\n" in value or len(value) > 120:
            formatted = escape(value).replace("\n", "<br>")
            sections.append(f"<p><strong>{label}</strong><br>{formatted}</p>")
        else:
            rows.append(f"<tr><th>{label}</th><td>{escape(value)}</td></tr>")
    if rows:
        html_parts.extend(('<table class="galaris-table-gray galaris-table-minimal"><tbody>', *rows, "</tbody></table>"))
    html_parts.extend(sections)
    html_parts.append(f"<blockquote><p>{escape(decision_scope)}</p></blockquote>")
    body_html = "".join(html_parts)
    return body, body_html if len(body_html) <= _NOTIFICATION_LIMIT else None
