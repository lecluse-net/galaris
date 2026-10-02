import type { ConnectionParamDef, ConnectionParamOption } from './services/toolService'

const BUILT_IN_TOOL_CODES = new Set([
  "galaris",
  "conversation",
  "memory",
  "file_sharing",
  "galaris_admin",
  "tool_admin",
  "agent_admin",
  "goal_management",
  "skill_management",
  "process_admin",
  "topic",
  "search",
  "browser",
  "chat",
  "console",
  "mail",
  "calendar",
  "n8n",
  "image",
  "audio",
  "voice",
  "multimedia",
  "messenger",
  "matrix",
  "telegram",
  "whatsapp",
  "one_bot",
  "nextcloud_talk",
  "nextcloud",
  "grav",
  "affine"
])

const CONNECTION_PARAM_CODES: Record<string, ReadonlySet<string>> = {
  browser: new Set(['default_output', 'allow_local_network', 'network_filter_mode', 'network_filter', 'permission_methods']),
  mail: new Set([
    'email_address', 'password',
    'imap_host', 'imap_port', 'imap_security',
    'smtp_host', 'smtp_port', 'smtp_security',
    'connect_timeout_s', 'operation_timeout_s', 'poll_interval_s',
    'max_attachment_mb', 'max_total_attachment_mb',
    'approval_required', 'approver_user_id',
  ]),
  calendar: new Set([
    'timezone', 'workday_start', 'workday_end', 'slot_step_minutes',
  ]),
  messenger: new Set([
    'login', 'user_id', 'password', 'access_token',
    'bot_token', 'allowed_user_ids', 'allowed_chat_ids', 'require_group_mention',
    'phone_number_id', 'business_account_id', 'allowed_phone_numbers',
    'template_name', 'template_language', 'allowed_room_ids', 'auto_join_invites',
  ]),
  nextcloud_talk: new Set([
    'login', 'password',
  ]),
  matrix: new Set([
    'user_id', 'access_token', 'password', 'allowed_user_ids', 'allowed_room_ids',
    'require_group_mention', 'auto_join_invites',
  ]),
  one_bot: new Set(['user_id', 'password']),
  telegram: new Set([
    'bot_token', 'allowed_user_ids', 'allowed_chat_ids', 'require_group_mention',
  ]),
  whatsapp: new Set([
    'access_token', 'phone_number_id', 'business_account_id', 'allowed_phone_numbers',
    'template_name', 'template_language',
  ]),
}

export function toolMessageKey(code: string, field: 'label' | 'description'): string | null {
  return BUILT_IN_TOOL_CODES.has(code) ? `tools.builtins.${code}.${field}` : null
}

export function connectionParamMessageKey(toolCode: string, name: string, definition?: Partial<ConnectionParamDef>): string | null {
  if (definition?.builtin && definition.description?.startsWith('tools.')) return definition.description
  return CONNECTION_PARAM_CODES[toolCode]?.has(name)
    ? `tools.connectionParamDescriptions.${toolCode}.${name}`
    : null
}

export function connectionParamLabel(
  toolCode: string | undefined,
  name: string,
  definition: Partial<ConnectionParamDef>,
  translate: (key: string) => string,
  exists: (key: string) => boolean,
): string {
  const key = definition.label?.trim() || `tools.connectionParamLabels.${name}`
  if ((definition.builtin || toolCode && BUILT_IN_TOOL_CODES.has(toolCode)) && exists(key)) return translate(key)
  return definition.label?.trim() || name
}

export function connectionParamOptions(
  toolCode: string | undefined,
  name: string,
  definition: Partial<ConnectionParamDef>,
  translate: (key: string) => string,
  exists: (key: string) => boolean,
): ConnectionParamOption[] {
  return (definition.options ?? []).map(option => {
    const key = option.label || `tools.connectionParamOptions.${toolCode}.${name}.${option.value}`
    return {
      value: option.value,
      label: (definition.builtin || toolCode && BUILT_IN_TOOL_CODES.has(toolCode)) && exists(key)
        ? translate(key) : option.label || option.value,
    }
  })
}

export function sortedConnectionParamEntries<T extends { order?: number | null }>(
  params: Record<string, T>,
): Array<[string, T]> {
  return Object.entries(params).sort(([leftName, left], [rightName, right]) => {
    const leftOrder = left.order ?? Number.MAX_SAFE_INTEGER
    const rightOrder = right.order ?? Number.MAX_SAFE_INTEGER
    return leftOrder - rightOrder || leftName.localeCompare(rightName)
  })
}
