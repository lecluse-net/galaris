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
}

export async function listPermissions(params: { agent_id?: number; allowed?: boolean; offset: number; limit: number }, signal?: AbortSignal) {
  return (await api.get<{ items: RememberedPermission[]; total: number }>('/messenger/permissions', { params, signal })).data
}

export async function deletePermission(id: string) {
  await api.delete(`/messenger/permissions/${id}`)
}

export interface ActionAuthorization {
  id: string
  agent_id: number
  approver_user_id: number
  source: 'mcp' | 'runtime' | 'domain'
  capability_kind: 'tool' | 'resource' | 'prompt'
  capability_name: string
  status: 'pending' | 'approved' | 'denied' | 'expired' | 'invalidated' | 'executing' | 'completed' | 'failed' | 'outcome_unknown'
  preview: string
  decision_source: 'human' | 'agent_yolo' | null
  created_at: string
  expires_at: string
  notification_failed?: boolean
  can_answer?: boolean
  can_remember?: boolean
  can_cancel?: boolean
  arguments?: Record<string, unknown>
}

export async function listActionAuthorizations(params: { agent_id?: number; status?: string; offset: number; limit: number }, signal?: AbortSignal) {
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
