from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.llm.timing import LLMProcessingTiming, execution_timing


@pytest.mark.parametrize("unfinished", [False, True])
def test_first_output_unions_overlaps_and_leaves_missing_end_evidence_unknown(unfinished):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    def at(seconds):
        return start + timedelta(seconds=seconds)

    calls = [
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(0),
            completed_at=None if unfinished else at(5), seconds=5),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(2),
            completed_at=at(6), seconds=4),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(8),
            completed_at=None, seconds=0, first_output_at=at(10)),
        LLMProcessingTiming(call_id=uuid4(), purpose="agent.exec", started_at=at(20),
            completed_at=at(25), seconds=5, first_output_at=at(23)),
    ]
    result = execution_timing(calls)
    assert result.first_output_seconds == 10
    assert result.call_seconds_before_output == (None if unfinished else 8)
    assert result.between_calls_seconds == (None if unfinished else 2)
    assert execution_timing(calls[:2]).first_output_seconds is None
    assert execution_timing([]).first_call_at is None
