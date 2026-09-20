import type { JsonSchema } from './services/labWorkbenchService'

export const parameterGroups = [
  { key: 'general', icon: 'tune', fields: ['label', 'language', 'source_kind', 'agent', 'sender', 'agent_id', 'owner_agent_id', 'title', 'datetime', 'weekday', 'location', 'channel', 'message_platform', 'message_type', 'room_id', 'message_group_id'] },
  { key: 'behavior', icon: 'account_tree', fields: ['effort', 'forced_route', 'forced_effort', 'auto_approve', 'driver_code', 'pipeline_policy', 'can_clarify', 'delivery_owner', 'max_depth', 'max_nodes', 'max_leaves', 'route', 'model_code', 'sequence', 'referrer_max_reminders', 'window_messages', 'context_characters', 'continuity_threshold', 'prior', 'ranking_limit', 'title_weight', 'content_weight', 'output_attempts', 'current_task_runtime_settings'] },
  { key: 'instructions', icon: 'subject', fields: ['system_prompt', 'language_instruction', 'prompts', 'shared_context', 'objective', 'description', 'user_context', 'briefing', 'tracking_content', 'latest_task_objective', 'interrupted_objective', 'context_projection', 'linked_work', 'result_contract'] },
  { key: 'history', icon: 'history', fields: ['messages', 'history', 'clarifications', 'initial_topic', 'topic', 'topics', 'message_context', 'speaker_context'] },
  { key: 'resources', icon: 'folder_open', fields: ['attachments', 'recent_attachments', 'recent_images', 'resources', 'tool_catalog', 'tool_catalog_version', 'available_tools', 'available_processes', 'existing_memories', 'memories', 'injected_memory_ids', 'working_set', 'active_skills', 'tool_responses'] },
  { key: 'context', icon: 'data_object', fields: ['data', 'task_uri', 'parent_id', 'origin', 'referrer', 'plan', 'agent_configuration'] },
] as const

const multilineFields = new Set([
  'system_prompt', 'language_instruction', 'shared_context', 'objective', 'description',
  'user_context', 'briefing', 'tracking_content', 'latest_task_objective',
  'interrupted_objective', 'context_projection', 'linked_work',
])

export function isMultilineParameter(name: string): boolean {
  return multilineFields.has(name)
}

/** Resolve local schema references without changing the request or its values. */
export function resolveParameterSchema(field: JsonSchema, root: JsonSchema): JsonSchema {
  const seen = new Set<string>()
  let resolved = field
  for (;;) {
    const ref = resolved.$ref
    if (ref?.startsWith('#/$defs/') && !seen.has(ref)) {
      seen.add(ref)
      const definition = root.$defs?.[ref.slice('#/$defs/'.length)]
      if (definition) { resolved = { ...definition, ...resolved, $ref: undefined }; continue }
    }
    const variant = resolved.anyOf?.find(item => item.type !== 'null')
    if (variant) { resolved = { ...resolved, ...variant, anyOf: undefined }; continue }
    return resolved
  }
}

export function isStructuredParameter(schema: JsonSchema): boolean {
  return !schema.enum && !['boolean', 'integer', 'number', 'string'].includes(schema.type ?? '')
}
