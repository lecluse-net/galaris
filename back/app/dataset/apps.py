"""Dataset operations for consented HTML applications; the host checks its document."""

from typing import Any, cast
from uuid import UUID
from sqlalchemy import select
from app.agent import AgentManagementScope
from app.document import AppConsentRequired, AppWriteLimitError
from core.database import get_db
from .models import Dataset, DatasetAppConsent, DatasetAlias
from . import service


async def binding(uri: str, actor: AgentManagementScope, *, write: bool = False) -> Dataset:
    from app.file_share import parse_resource_uri
    reference = parse_resource_uri(uri)
    if reference.scheme not in {"data", "document"} or len(reference.segments) != 1:
        raise ValueError("Use an exact Dataset URI")
    identity = UUID(reference.locator)
    if reference.scheme == "document":
        alias = await get_db().scalar(select(DatasetAlias).where(DatasetAlias.legacy_document_id == identity))
        if alias is None:
            raise service.DatasetNotFoundError("No verified Dataset alias exists")
        identity = alias.dataset_id
    return await service.record(identity, actor, write=write, lock=write)


async def consent(document_id: UUID, app: str, alias: str, user_id: int) -> DatasetAppConsent | None:
    return await get_db().scalar(select(DatasetAppConsent).where(DatasetAppConsent.document_id == document_id,
        DatasetAppConsent.app_key == app, DatasetAppConsent.alias == alias, DatasetAppConsent.user_id == user_id)
        .execution_options(populate_existing=True))


async def application(operation: str, actor: AgentManagementScope, context: dict[str, Any]) -> dict[str, Any]:
    document_id, revision = UUID(context["document_id"]), context["document_revision"]
    apps: list[dict[str, Any]] = context["apps"]
    if operation == "permissions":
        grants: list[dict[str, Any]] = []
        for app in apps:
            for alias, declaration in app["datasets"].items():
                grant = await consent(document_id, app["id"], alias, actor.user_id)
                identity = UUID(declaration["uri"].split("://", 1)[1])
                approved = grant.access if grant and grant.dataset_id == identity and grant.document_revision == revision else None
                title = None
                try:
                    title = (await binding(declaration["uri"], actor)).title
                except (service.DatasetNotFoundError, service.DatasetPermissionError):
                    pass
                grants.append({"app_key": app["id"], "app_title": app["title"], "alias": alias,
                    "dataset_id": str(identity), "dataset_uri": f"data://{identity}", "dataset_title": title, "requested_access": declaration["access"], "access": approved})
        return {"document_revision": revision, "grants": grants}
    app_key, alias, request = context["app_key"], context["alias"], context["request"]
    if request["document_revision"] != revision:
        raise service.DatasetConflictError("The application changed; review its permissions again")
    app = next((app for app in apps if app["id"] == app_key), None)
    declaration = app["datasets"].get(alias) if app else None
    write = request.get("access") == "write" if operation == "consent" else request["operation"] != "read"
    if declaration is None or write and declaration["access"] != "write":
        raise service.DatasetPermissionError("Dataset operation is not declared by this application")
    grant = await consent(document_id, app_key, alias, actor.user_id)
    if operation == "consent" and request["access"] is None:
        if grant:
            grant.access = None
        await get_db().commit()
        return await application("permissions", actor, context)
    dataset = await binding(declaration["uri"], actor, write=write)
    if operation == "consent":
        if grant is None:
            grant = DatasetAppConsent(document_id=document_id, dataset_id=dataset.id, user_id=actor.user_id, app_key=app_key, alias=alias)
            get_db().add(grant)
        grant.dataset_id, grant.document_revision, grant.access = dataset.id, revision, request["access"]
        await get_db().commit()
        return await application("permissions", actor, context)
    if grant is None or grant.dataset_id != dataset.id or grant.document_revision != revision or grant.access is None or write and grant.access != "write":
        raise AppConsentRequired("Approve this application's Dataset access in document permissions")
    value = service.parse_json(dataset.content)
    if write:
        if request["expected_revision"] != dataset.revision:
            raise service.DatasetConflictError("Read the Dataset's current revision before writing")
        if request["operation"] == "append":
            if not isinstance(value, list):
                raise ValueError("Append requires a Dataset whose root is a JSON array")
            cast(list[Any], value).append(request["value"])
        else:
            value = request["value"]
        content = service.encode(value)
        service.parse_json(content)
        try:
            await service.reserve_budget(actor.user_id, dataset.id, len(content.encode()))
        except service.DatasetWriteLimitError as exc:
            raise AppWriteLimitError(str(exc)) from exc
        await service.replace(dataset.id, actor, content=content, expected_revision=dataset.revision)
        await get_db().commit()
    return {"revision": dataset.revision, "data": value}
