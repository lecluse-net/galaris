"""Shared projections for HTTP and administrative MCP incident reads."""

from .models import FailureIncident, FailureIncidentTrace, FailurePattern
from .schemas import FailureIncidentDetail, FailureIncidentRead, FailurePatternRead


def incident_read(row: FailureIncident, pattern: FailurePattern) -> FailureIncidentRead:
    return FailureIncidentRead(
        id=row.id,
        pattern_id=row.pattern_id,
        pattern_status=pattern.status,
        pattern_occurrence_count=pattern.occurrence_count,
        causal_incident_id=row.causal_incident_id,
        idempotency_key=row.idempotency_key,
        kind=row.kind,
        category=row.category,
        phase=row.phase,
        severity=row.severity,
        error_type=row.error_type,
        error_code=row.error_code,
        error_message=row.error_message,
        retryable=row.retryable,
        attempt_number=row.attempt_number,
        retry_limit=row.retry_limit,
        will_retry=row.will_retry,
        recovered_at=row.recovered_at,
        task_id=row.task_id,
        task_attempt_id=row.task_attempt_id,
        llm_call_id=row.llm_call_id,
        conversation_round_id=row.conversation_round_id,
        process_run_id=row.process_run_id,
        agent_id=row.agent_id,
        run_uuid=row.run_uuid,
        driver_code=row.driver_code,
        provider_code=row.provider_code,
        model_code=row.model_code,
        tool_name=row.tool_name,
        tool_call_external_id=row.tool_call_external_id,
        occurred_at=row.occurred_at,
        created_at=row.created_at,
    )


def incident_detail(
    incident: FailureIncident, pattern: FailurePattern, trace: FailureIncidentTrace,
) -> FailureIncidentDetail:
    return FailureIncidentDetail(
        **incident_read(incident, pattern).model_dump(),
        pattern=FailurePatternRead.model_validate(pattern),
        trace_schema_version=trace.schema_version,
        trace=trace.payload,
        redacted_fields=trace.redacted_fields,
        truncated_fields=trace.truncated_fields,
        trace_content_hash=trace.content_hash,
        trace_byte_size=trace.byte_size,
    )
