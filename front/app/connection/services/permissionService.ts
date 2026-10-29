import api from '@/core/api'

export interface RememberedPermission {
  id: string
  agent_id: number
  permission_key: string
  question: string
  allowed: boolean | null
  approver_user_id: number
  approver_label: string
  created_at: string
  answered_at: string | null
  can_answer?: boolean
  can_decide?: boolean
  active?: boolean
  options?: { id: string; label: string }[]
}

export async function listPermissions(params: { agent_id?: number; allowed?: boolean; pending?: boolean; q?: string; offset: number; limit: number }, signal?: AbortSignal) {
  return (await api.get<{ items: RememberedPermission[]; total: number; counts?: Record<string, number> }>('/messenger/permissions', { params, signal })).data
}

export async function answerPermission(id: string, option_id: string) {
  await api.post(`/messenger/permissions/${id}/answer`, { option_id })
}

export async function deletePermission(id: string) {
  await api.delete(`/messenger/permissions/${id}`)
}

export interface ActionAuthorization {
  id: string
  agent_id: number
  approver_user_id: number
  source: 'mcp' | 'runtime' | 'domain'
  runtime: string
  capability_kind: 'tool' | 'resource' | 'prompt'
  capability_name: string
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'invalidated' | 'executing' | 'completed' | 'failed' | 'outcome_unknown'
  preview: string
  decision_source: string | null
  remembered?: boolean
  created_at: string
  expires_at: string
  notification_failed?: boolean
  can_answer?: boolean
  can_remember?: boolean
  can_cancel?: boolean
  arguments?: Record<string, unknown>
  presentation?: { title: string; fields: { label: string; value: string }[] }
}

export async function listActionAuthorizations(params: { agent_id?: number; status?: string; q?: string; offset: number; limit: number }, signal?: AbortSignal) {
  return (await api.get<{ items: ActionAuthorization[]; total: number }>('/tools/action-authorizations', { params, signal })).data
}

export async function getActionAuthorization(id: string, signal?: AbortSignal) {
  return (await api.get<ActionAuthorization>(`/tools/action-authorizations/${id}`, { signal })).data
}

export async function answerActionAuthorization(id: string, approved: boolean, remember = false) {
  await api.post(`/tools/action-authorizations/${id}/answer`, { approved, ...(remember ? { remember: true } : {}) })
}

export async function cancelActionAuthorization(id: string) {
  await api.post(`/tools/action-authorizations/${id}/cancel`)
}

export interface RuntimePermission {
  id: string
  agent_id: number
  runtime: string
  capability_name: string
  created_at: string
  active: boolean
  allowed: boolean
  can_revoke: boolean
}

export interface FunctionPermission {
  id: string
  agent_id: number
  connection_id: number
  tool_label: string
  capability_name: string
  active: boolean
  allowed: boolean
  can_revoke: boolean
}

export async function listFunctionPermissions(params: { agent_id?: number; offset: number; limit: number }, signal?: AbortSignal) {
  return (await api.get<{ items: FunctionPermission[]; total: number }>('/connections/function-permissions', { params, signal })).data
}

export async function revokeFunctionPermission(permission: FunctionPermission) {
  await api.put(`/connections/${permission.connection_id}/functions/${encodeURIComponent(permission.capability_name)}`, { state: 'ask', capability_kind: 'tool' })
}

export async function listRuntimePermissions(params: { agent_id?: number; offset: number; limit: number }, signal?: AbortSignal) {
  return (await api.get<{ items: RuntimePermission[]; total: number }>('/tools/action-authorizations/runtime-permissions', { params, signal })).data
}

export async function revokeRuntimePermission(id: string) {
  await api.delete(`/tools/action-authorizations/runtime-permissions/${id}`)
}
