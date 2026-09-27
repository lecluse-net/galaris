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
