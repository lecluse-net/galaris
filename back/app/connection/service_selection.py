"""Resolve agent-facing Service codes to private, account-scoped connection identities."""

from collections.abc import Collection

from sqlalchemy import select

from core.database import get_db
from .models import Connection
from .parameter_resolution import effective_param_value_expression


async def service_codes_for_connections(connection_ids: Collection[int]) -> dict[int, str]:
    """Project private account references to public Service codes in a single query."""
    from app.services import ServiceModel

    if not connection_ids:
        return {}
    rows = await get_db().execute(select(Connection.id, ServiceModel.code)
        .join(ServiceModel, ServiceModel.id == Connection.service_id).where(Connection.id.in_(connection_ids)))
    return dict(rows.tuples().all())


async def account_emails_for_connections(connection_ids: Collection[int]) -> dict[int, str]:
    """Read only the public mailbox address, including inherited and forced values."""
    from app.services import ServiceModel

    if not connection_ids:
        return {}
    db = get_db()
    rows = await db.execute(select(Connection.id, ServiceModel.mail_config)
        .join(ServiceModel, ServiceModel.id == Connection.service_id)
        .where(Connection.id.in_(connection_ids), ServiceModel.mail_config.is_not(None)))
    by_parameter: dict[str, list[int]] = {}
    for identifier, config in rows.tuples():
        if config is not None:
            name = config.get("param_map", {}).get("email_address", "email_address")
            by_parameter.setdefault(name, []).append(identifier)
    addresses: dict[int, str] = {}
    for name, ids in by_parameter.items():
        value = effective_param_value_expression(ServiceModel.global_params, ServiceModel.connection_schema, Connection.id, name)
        result = await db.execute(select(Connection.id, value).join(ServiceModel, ServiceModel.id == Connection.service_id)
            .where(Connection.id.in_(ids), ServiceModel.connection_schema["params"][name]["type"].astext.is_distinct_from("password")))
        addresses.update((identifier, address or "") for identifier, address in result.tuples())
    return addresses


async def resolve_service_connection(agent_id: int, service_code: str, *, account_email: str | None = None,
                                     active_only: bool = True) -> Connection:
    from app.services import ServiceModel

    query = select(Connection).join(ServiceModel, ServiceModel.id == Connection.service_id).where(
        Connection.agent_id == agent_id, ServiceModel.code == service_code)
    if active_only:
        query = query.where(Connection.active.is_(True))
    matches = list(await get_db().scalars(query.execution_options(populate_existing=True)))
    if account_email is not None:
        addresses = await account_emails_for_connections([row.id for row in matches])
        address = account_email.strip().casefold()
        matches = [row for row in matches if row.id in addresses and addresses[row.id].casefold() == address]
    if not matches:
        raise ValueError("No matching Service account is available for this agent.")
    if len(matches) != 1:
        raise ValueError("Several accounts match this service_code. Specify a unique account_email.")
    return matches[0]
