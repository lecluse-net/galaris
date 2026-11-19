"""Read-only evidence for a single n8n Data Tables insertion."""

import json
import re
from uuid import UUID

from pydantic import JsonValue

from .authorization import canonical
from .rest_contracts import RestRequest, RestRequestRejected, RestResponse

REFERENCE_COLUMN = "operation_reference"


def insert_row(request: RestRequest) -> dict[str, JsonValue] | None:
    if request.method != "POST" or not re.fullmatch(r"/?data-tables/[A-Za-z0-9_-]{1,128}/rows", request.path):
        return None
    body = request.json_body
    if request.headers or request.params or not isinstance(body, dict) or set(body) - {"data", "returnType"}:
        return None
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    if any(isinstance(value, (dict, list)) for value in row.values()):
        return None
    if REFERENCE_COLUMN in row:
        raise RestRequestRejected("The operation_reference column is reserved for the REST receipt")
    return row


def insert_with_reference(request: RestRequest, row: dict[str, JsonValue], reference: UUID) -> RestRequest:
    assert isinstance(request.json_body, dict)
    return request.model_copy(update={"json_body": {**request.json_body,
        "data": [{**row, REFERENCE_COLUMN: str(reference)}]}})


def lookup_request(path: str, reference: UUID) -> RestRequest:
    return RestRequest(path=path, params={"limit": 2, "filter": json.dumps({"type": "and", "filters": [
        {"columnName": REFERENCE_COLUMN, "condition": "eq", "value": str(reference)},
    ]})})


def confirmed_row_id(response: RestResponse, row: dict[str, JsonValue], reference: UUID) -> int | None:
    body = response.body
    if response.status_code != 200 or not isinstance(body, dict) or "nextCursor" not in body or body["nextCursor"] is not None:
        return None
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        return None
    actual = rows[0]
    identifier = actual.get("id")
    if type(identifier) is not int or identifier <= 0 or actual.get(REFERENCE_COLUMN) != str(reference):
        return None
    if not row.keys() <= actual.keys() or canonical({name: actual[name] for name in row}) != canonical(row):
        return None
    return identifier
