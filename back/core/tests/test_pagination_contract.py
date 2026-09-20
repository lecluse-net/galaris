"""Public list pagination stays consistent across domains."""

from typing import Any

from main import app


def _query_schema(path: str, name: str) -> dict[str, Any]:
    fastapi_app = app.other_asgi_app
    operation = fastapi_app.openapi()["paths"][path]["get"]
    parameter = next(
        item for item in operation["parameters"] if item["name"] == name
    )
    return parameter["schema"]


def test_paginated_lists_default_to_50_and_accept_500() -> None:
    contracts = (
        ("/api/auth/users", "limit"),
        ("/api/authorize/assignments", "limit"),
        ("/api/agents", "limit"),
        ("/api/agents/titles", "limit"),
        ("/api/agents/groups", "limit"),
        ("/api/tasks", "limit"),
        ("/api/tasks/recent", "limit"),
        ("/api/connections", "limit"),
        ("/api/evaluation/candidates", "limit"),
        ("/api/goals", "limit"),
        ("/api/goals/{goal_id}/cycles", "page_size"),
        ("/api/processes/runs", "page_size"),
    )

    for path, parameter_name in contracts:
        schema = _query_schema(path, parameter_name)
        assert schema["default"] == 50, path
        assert schema["maximum"] == 500, path
