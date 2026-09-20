from __future__ import annotations

import json

from core.database.database import serialize_json_for_postgresql


def test_postgresql_json_serializer_removes_only_actual_nested_nuls() -> None:
    serialized = serialize_json_for_postgresql(
        {
            "nul\x00key": [
                "before\x00after",
                {"nested": "\x00", "literal_escape": r"\u0000"},
            ],
            "unchanged": "Galaris",
        }
    )

    assert json.loads(serialized) == {
        "nulkey": [
            "beforeafter",
            {"nested": "", "literal_escape": r"\u0000"},
        ],
        "unchanged": "Galaris",
    }
