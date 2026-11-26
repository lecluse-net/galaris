"""Immutable comparison data for a committed driver checkpoint."""

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

from pydantic_core import to_json


@dataclass(frozen=True)
class CheckpointIndex:
    driver: str
    run: str
    fields: Mapping[str, tuple[bytes, ...]]

    @classmethod
    def capture(cls, driver: str, run: str, data: Mapping[str, Any]) -> "CheckpointIndex":
        fields: dict[str, tuple[bytes, ...]] = {}
        for name in ("message_history", "effects"):
            values = data.get(name)
            if isinstance(values, list):
                fields[name] = tuple(sha256(to_json(item)).digest() for item in cast(list[Any], values))
        return cls(driver, run, fields)

    def unchanged_prefixes(self, previous: "CheckpointIndex | None") -> dict[str, int]:
        if previous is None or (self.driver, self.run) != (previous.driver, previous.run):
            return {}
        prefixes: dict[str, int] = {}
        for name, values in self.fields.items():
            count = 0
            for current, old in zip(values, previous.fields.get(name, ())):
                if current != old:
                    break
                count += 1
            if count:
                prefixes[name] = count
        return prefixes
