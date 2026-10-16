"""Synthetic model answers; the real Chat, controller, tools and Process engine run normally."""

import json
import re

from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart, ToolReturnPart
from pydantic_ai.models.function import DeltaToolCall

from tests.e2e_conversation_control import ControlledModel

agents = set()


async def build_model(_llm, **_kwargs):
    def answer(messages, info):
        if any(isinstance(part, ToolReturnPart) and part.tool_name == "conversation_process_respond"
               for part in messages[-1].parts):
            return ModelResponse(parts=[TextPart("Votre réponse a été enregistrée dans le processus.")])
        prompt = str(info.instructions) + str(messages)
        references = re.findall(r"reference=#([A-F0-9]+) kind=process_human_activity", prompt)
        if not references:
            return ModelResponse(parts=[TextPart("Aucune demande de processus en attente.")])
        if '"name": "report"' in prompt:
            files = re.findall(r"chat://[^/\s]+/[0-9a-f-]{36}", prompt)
            assert files, "The real controller must preserve the file-only message URI"
            output = {"report": {"type": "File", "value": files[-1]}}
        elif '"name": "accepted"' in prompt:
            output = {"accepted": {"type": "bool", "value": False}}
        else:
            output = {"text": "Approved synthetic note"}
        return ModelResponse(parts=[ToolCallPart("conversation_process_respond",
            {"reference": references[0], "output": output})])
    async def stream(messages, info):
        result = answer(messages, info)
        for part in result.parts:
            if isinstance(part, TextPart):
                yield part.content
            elif isinstance(part, ToolCallPart):
                yield {0: DeltaToolCall(name=part.tool_name, json_args=json.dumps(part.args),
                    tool_call_id=part.tool_call_id)}
    return ControlledModel(function=answer, stream_function=stream)
