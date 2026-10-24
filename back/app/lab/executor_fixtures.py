"""Argument-scoped responses for effect-free executor qualification."""

from typing import Any, cast

from .executor_outcomes import contains_json


class ToolFixtureSequence:
    """Keep unrelated targets from consuming each other's ordered evidence."""

    def __init__(self, responses: list[Any], arguments: list[dict[str, Any]] | None = None) -> None:
        if arguments is not None and len(arguments) != len(responses):
            raise ValueError("Fixture argument guards must align with their response sequence")
        self.responses = responses
        self.arguments: list[dict[str, Any]] = arguments if arguments is not None else [dict[str, Any]() for _ in responses]
        self.consumed: set[int] = set()

    def has_remaining(self, arguments: dict[str, Any]) -> bool:
        return any(index not in self.consumed and contains_json(arguments, guard)
                   for index, guard in enumerate(self.arguments))

    def take(self, arguments: dict[str, Any]) -> Any:
        for index, guard in enumerate(self.arguments):
            if index not in self.consumed and contains_json(arguments, guard):
                self.consumed.add(index)
                return self.responses[index]
        return {"success": False, "error": "simulation_fixture_unavailable"}


class ExecutorToolResponses:
    """Replay declared receipts and permit verification of this case's own writes."""

    def __init__(self, responses: dict[str, list[Any]], arguments: dict[str, list[dict[str, Any]]]) -> None:
        self.sequences = {name: ToolFixtureSequence(values, arguments.get(name)) for name, values in responses.items()}
        self.written: dict[str, dict[str, Any]] = {}

    def take(self, name: str, arguments: dict[str, Any]) -> Any:
        uri = arguments.get("uri")
        sequence = self.sequences.get(name)
        if sequence is not None and sequence.has_remaining(arguments):
            result = sequence.take(arguments)
            if name == "file_read" and isinstance(uri, str):
                # Scripted reads may model revocation or an external writer. Never
                # replace that evidence with an earlier local write, even on retry.
                self.written.pop(uri, None)
        elif name == "file_read" and isinstance(uri, str) and uri in self.written:
            return dict(self.written[uri])
        else:
            result = {"success": False, "error": "simulation_fixture_unavailable"}
        if (name in {"file_create", "file_edit"} and isinstance(result, dict)
                and isinstance(arguments.get("content"), str)):
            receipt = cast(dict[str, Any], result)
            if receipt.get("success") is not False and not receipt.get("error"):
                target = receipt.get("uri") or (uri if name == "file_edit" else None)
                if isinstance(target, str):
                    self.written[target] = {"uri": target, "content": arguments["content"],
                                            "revision": receipt.get("revision"), "complete": True}
        return cast(Any, result)
