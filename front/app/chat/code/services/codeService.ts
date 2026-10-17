import { api } from '@/core/api'
import { isAxiosError } from 'axios'
import type { CodeRecovery, CodeSession, CodeWorkspace, EditorMode, RepositoryCandidates } from '../types'

export function codeErrorTranslationKey(error: unknown): string {
  const detail = isAxiosError<{ detail?: unknown }>(error) ? error.response?.data.detail : null
  if (detail === 'code_runtime_not_configured') return 'code.runtimeNotConfigured'
  if (detail === 'code_directory_not_repository') return 'code.directoryNotRepository'
  if (detail === 'code_discovery_forbidden') return 'code.discoveryForbidden'
  return 'code.error'
}

export const codeService = {
  async discover(room: string, signal?: AbortSignal): Promise<RepositoryCandidates> { return (await api.get<RepositoryCandidates>(`/chat/rooms/${room}/repositories`, { signal })).data },
  async register(room: string, path: string): Promise<CodeWorkspace> { return (await api.post<CodeWorkspace>(`/chat/rooms/${room}/repositories`, undefined, { params: { uri: `console://${path.split('/').map(encodeURIComponent).join('/')}/` } })).data },
  async list(room: string): Promise<CodeWorkspace[]> { return (await api.get<CodeWorkspace[]>(`/code/rooms/${room}`)).data },
  async open(id: string, mode?: EditorMode): Promise<CodeSession> { return (await api.post<CodeSession>(`/code/workspaces/${id}/sessions`, { mode })).data },
  async touch(id: string): Promise<CodeWorkspace> { return (await api.post<{ workspace: CodeWorkspace }>(`/code/sessions/${id}/heartbeat`)).data.workspace },
  async resume(id: string): Promise<CodeRecovery> { return (await api.post<CodeRecovery>(`/code/sessions/${id}/resume`)).data },
  async navigate(id: string, file?: string, view = 'changes'): Promise<void> { await api.post(`/code/sessions/${id}/navigate`, { file, view }) },
}
