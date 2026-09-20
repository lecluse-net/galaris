export const agent = { id: 7, code: 'alice', first_name: 'Alice', last_name: 'Example', agent_driver: 'pydantic_ai', user_id: 1, user: { id: 1, email: 'test@example.invalid', display_name: 'Test User', is_current_user: true }, is_owner: true, memory_item_id: null, title_id: 1, group_id: null, task_harness_id: null, profile_id: null, voice: null, personality: 'Precise and helpful', job_description: 'An agent for testing', job_title: 'Assistant', has_avatar: false }
export const call = {
  id: 'call-1', purpose: 'agent.execution', provider_name: 'Example', requested_model: 'model-a', effective_model: 'model-a', reasoning_effort: 'high',
  call_type: 'chat', status: 'completed', stream: true, request_messages: [], prompt: 'User request', system_prompt: 'System instructions',
  response_text: 'Final answer', reasoning: '', tool_calls: [], raw_response: 'PRIVATE RAW TRANSPORT', finish_reason: 'stop', usage: { output_tokens: 17 },
  input_tokens: 101, output_tokens: 17, total_tokens: 118, cache_read_tokens: 23, cache_write_tokens: 0, reasoning_tokens: 0,
  cost: 0.000123, inference_cost: 0.000456, cost_estimated: false, is_subscription: true,
  started_at: '2026-09-01T12:00:00Z', completed_at: '2026-09-01T12:00:01Z', duration: 1, created_at: '2026-09-01T12:00:00Z', updated_at: null,
}
export const result = { prompt: 'Objective', system_prompt: 'Instructions', messages: [], execution_time: 1, result: 'Done', cost: 0, tools_used: [], metadata: {}, success: true }
export const document = {
  document_type: 'html',
  id: 'doc-a', revision: 3, lock_version: 3, owner_agent_id: 7, owner_user_id: null, provider_code: 'galaris', title: 'Test document',
  memory_type: 'working', node_kind: 'document', content_type: 'text', media_type: 'text/markdown', filename: null, keywords: [], metadata: { folder: 'Reports' },
  visibility: 'private', global_access: 0, read_only: false, deletion_protected: false, source_managed: false, managed_source_kind: null, managed_source_ref: null,
  content_hash: 'example', size_bytes: 10, last_accessed_at: null, access_count: 0, valid_from: null, valid_until: null, old_at: null, old_reason: null,
  created_at: '2026-09-01T12:00:00Z', updated_at: null, access: { can_read: true, can_write: true }, grants: [], payload: { text: '# Report\n\nInitial body' }, source_refs: [],
}
export const goal = {
  id: 'goal-a', revision: 4, title: 'Publish report', description: 'Prepare the report', tracking_markdown: '', description_document_id: 'description-a', tracking_document_id: 'tracking-a',
  agent_id: 7, agent_name: 'Alice Example', agent_code: 'alice', referrer: null, cycle_delay_seconds: null, parent_goal_id: null, parent_title: null, children_count: 0,
  schedule_enabled: false, schedule: [], referrer_max_reminders: 3, status: 'ACTIVE', pause_reason: null, next_cycle_at: null, completed_at: null, last_error: null,
  cycle_count: 0, task_cost: 0, evaluation_cost: 0, total_cost: 0, current_task_id: null, last_task_finished_at: null, last_verdict: null, created_at: '2026-09-01T12:00:00Z', updated_at: null,
}
