"""Query expression for ordinary non-secret parameter inheritance."""

from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement

from .models import ConnectionParam


class RuntimeConnectionParams(dict[str, Any]):
    """Parameter values with a server-only connection identity for OAuth.

    The identity is not a dictionary entry: it is neither serialized nor
    forgeable by supplying parameters in an API request.
    """

    def __init__(self, values: dict[str, Any], connection_id: int, *, oauth_enabled: bool = False) -> None:
        super().__init__(values)
        self.connection_id = connection_id
        self.oauth_enabled = oauth_enabled


def effective_param_value_expression(
    global_params: InstrumentedAttribute[dict[str, Any] | None],
    schema: InstrumentedAttribute[dict[str, Any]],
    connection_id: InstrumentedAttribute[int],
    name: str,
) -> ColumnElement[str | None]:
    """Resolve imposed global, local override, global value, then schema default."""
    entry = global_params[name]
    global_value = func.nullif(entry["value"].astext, "")
    local_value = select(func.nullif(ConnectionParam.param_value, "")).where(
        ConnectionParam.connection_id == connection_id, ConnectionParam.param_name == name,
    ).correlate_except(ConnectionParam).scalar_subquery()
    default = func.nullif(schema["params"][name]["default"].astext, "")
    return case(
        (entry["forced"].as_boolean().is_(True) & global_value.is_not(None), global_value),
        else_=func.coalesce(local_value, global_value, default),
    )
