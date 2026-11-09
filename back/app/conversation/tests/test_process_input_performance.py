"""Measure the complete input path with a real DB and a synthetic model boundary."""

import json
from io import BytesIO
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import FunctionModel
import pytest
from sqlalchemy import func, select

from app.conversation.mcp import conversation_process_prepare, conversation_process_start
from app.conversation.tests.test_process_inputs import assessment, context, human, human_turn, workflow
from app.llm import llm_service, structured_service
from app.file_share import ResourceContext, resource_create
from app.process.models import ProcessRun, ProcessStartJob
from app.process.tests.test_native_bpmn import native as native  # noqa: F401
from app.process.values import Variable
from tests.sql_reads import measured_reads


@pytest.mark.asyncio
async def test_one_human_request_collects_verified_inputs_and_replays_without_repeated_inference(db, native, monkeypatch):
    owner, _ = native
    user = await human(db)
    picture = BytesIO(); Image.new("RGB", (8, 8), "white").save(picture, format="PNG")
    file = await resource_create(ResourceContext(agent_id=owner.id, runtime="internal"), "file://", picture.getvalue(), name="Synthetic.png")
    definition = await workflow(owner, [Variable(name="name", type="string", nullable=False),
        Variable(name="birth_date", type="date", nullable=False), Variable(name="portrait", type="File", nullable=False, mime_type="image/*")])
    expected = {"name": "Synthetic", "birth_date": "2000-02-29", "portrait": file.uri}
    calls = []
    def respond(_messages, info):
        properties = info.output_tools[0].parameters_json_schema.get("properties", {})
        collecting = "action" in properties
        calls.append("inputs" if collecting else "permission")
        payload = assessment() if collecting else {"launches": [{"workflow_id": definition.code, "input": expected}]}
        if "single_launch" in properties:
            payload["single_launch"] = True
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, payload)])
    monkeypatch.setattr(llm_service, "get_profile_llm", AsyncMock(return_value=SimpleNamespace(id=987)))
    monkeypatch.setattr(structured_service, "build_model_for_llm", AsyncMock(return_value=FunctionModel(respond)))
    monkeypatch.setattr(structured_service, "estimate_cost_from_usage", lambda *_: 0.0)
    turn, _ = await human_turn(db, owner, "Launch one synthetic dossier for Synthetic, born 2000-02-29, with this portrait.", user, files=[file.uri])
    started = time.perf_counter()
    async with measured_reads(db, "input-collection-replay") as reads:
        first = await conversation_process_prepare(context(turn), workflow_id=definition.code, input={"name": "Synthetic"})
        for _ in range(2):
            again = await conversation_process_prepare(context(turn), workflow_id=definition.code)
            assert again["run_id"] == first["run_id"]
        complete = await conversation_process_prepare(context(turn), workflow_id=definition.code,
            input={"birth_date": expected["birth_date"], "portrait": file.uri})
        assert complete["status"] == "ready"
        result = await conversation_process_start(context(turn), workflow_id=definition.code)
        replay = await conversation_process_start(context(turn), workflow_id=definition.code)
    assert result["run_id"] == replay["run_id"] == first["run_id"]
    assert result["started"] and not replay["started"]
    assert await db.scalar(select(func.count()).select_from(ProcessRun)) == 1
    assert await db.scalar(select(func.count()).select_from(ProcessStartJob)) == 1
    # Values added after intent assessment still require their final scope check.
    assert calls == ["inputs", "permission"]
    assert len(reads) <= 120
    print("INPUT_PREPARATION_MEASURE " + json.dumps({"llm_calls": len(calls), "purposes": calls,
        "sql_reads": len(reads), "seconds": round(time.perf_counter() - started, 6)}))
