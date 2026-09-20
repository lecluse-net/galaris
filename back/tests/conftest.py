"""Protocol fixtures shared by provider-boundary tests."""

from copy import deepcopy
import json

import pytest


@pytest.fixture
def responses_sse():
    """Emit a Responses stream with item deltas, including empty terminal output."""
    def encode(terminal, *, empty_terminal=False):
        events = [{"type": "response.created", "response": {
            **terminal, "status": "in_progress", "output": [], "usage": None,
        }}]
        for index, item in enumerate(terminal["output"]):
            initial = deepcopy(item)
            initial["status"] = "in_progress"
            if item["type"] == "function_call":
                initial["arguments"] = ""
            elif item["type"] == "message":
                initial["content"] = []
            elif item["type"] == "reasoning":
                initial["summary"] = []
                initial.pop("encrypted_content", None)
            events.append({"type": "response.output_item.added", "output_index": index, "item": initial})
            address = {"item_id": item["id"], "output_index": index}
            if item["type"] == "function_call":
                events.append({"type": "response.function_call_arguments.delta", **address, "delta": item["arguments"]})
                events.append({"type": "response.function_call_arguments.done", **address, "arguments": item["arguments"]})
            elif item["type"] == "message":
                for content_index, part in enumerate(item["content"]):
                    content_address = {**address, "content_index": content_index}
                    events.append({"type": "response.content_part.added", **content_address,
                        "part": {**part, "text": ""}})
                    events.append({"type": "response.output_text.delta", **content_address, "delta": part["text"]})
                    events.append({"type": "response.output_text.done", **content_address, "text": part["text"]})
                    events.append({"type": "response.content_part.done", **content_address, "part": part})
            elif item["type"] == "reasoning":
                for summary_index, part in enumerate(item["summary"]):
                    summary_address = {**address, "summary_index": summary_index}
                    events.append({"type": "response.reasoning_summary_part.added", **summary_address,
                        "part": {**part, "text": ""}})
                    events.append({"type": "response.reasoning_summary_text.delta", **summary_address, "delta": part["text"]})
                    events.append({"type": "response.reasoning_summary_text.done", **summary_address, "text": part["text"]})
                    events.append({"type": "response.reasoning_summary_part.done", **summary_address, "part": part})
            events.append({"type": "response.output_item.done", "output_index": index, "item": item})
        events.append({"type": "response.completed", "response": {
            **terminal, "output": [] if empty_terminal else terminal["output"],
        }})
        return "".join(f"data: {json.dumps({**event, 'sequence_number': index})}\n\n"
            for index, event in enumerate(events))

    return encode
