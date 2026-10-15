import api from '@/core/api'

export interface McpOAuthStatus {
  connected: boolean
  pending: boolean
  reconnect_required: boolean
  redirect_uri: string
}

export interface McpOAuthStart {
  method?: 'redirect' | 'device' | 'configure'
  authorization_url: string
  local_script?: string | null
  redirect_uri?: string
  device?: { state: string; user_code: string; verification_uri: string; interval: number } | null
}

export interface McpOAuthClient {
  client_id: string
  client_secret?: string
  token_endpoint_auth_method?: 'client_secret_basic' | 'client_secret_post'
}

const pendingKey = (state: string) => `galaris:mcp-oauth:${state}`
const localPendingPrefix = 'galaris:mcp-oauth-local:'

function rememberLocal(state: string, connectionId: number): void {
  // A workstation relay opens a new tab. Keep only a short-lived state-to-ID
  // association across tabs; tokens and PKCE verifiers never enter storage.
  for (const key of Object.keys(localStorage)) {
    if (!key.startsWith(localPendingPrefix)) continue
    try {
      const entry = JSON.parse(localStorage.getItem(key) ?? '{}') as { connectionId?: number; expires?: number }
      if (!entry.expires || entry.expires <= Date.now() || entry.connectionId === connectionId) localStorage.removeItem(key)
    } catch { localStorage.removeItem(key) }
  }
  localStorage.setItem(localPendingPrefix + state, JSON.stringify({ connectionId, expires: Date.now() + 600_000 }))
}

function localConnection(state: string): number {
  try {
    const entry = JSON.parse(localStorage.getItem(localPendingPrefix + state) ?? '{}') as { connectionId?: number; expires?: number }
    return entry.expires && entry.expires > Date.now() ? entry.connectionId ?? 0 : 0
  } catch { return 0 }
}

export const mcpOAuthService = {
  async status(connectionId: number): Promise<McpOAuthStatus> {
    return (await api.get<McpOAuthStatus>(`/connections/${connectionId}/oauth`)).data
  },
  async start(connectionId: number, client?: McpOAuthClient): Promise<McpOAuthStart> {
    const { data } = await api.post<McpOAuthStart>(`/connections/${connectionId}/oauth/start`, { browser_origin: window.location.origin, client })
    if (data.method === 'device' || data.method === 'configure') return data
    const state = new URL(data.authorization_url).searchParams.get('state')
    if (!state) throw new Error('Missing OAuth state')
    if (data.local_script) rememberLocal(state, connectionId)
    else sessionStorage.setItem(pendingKey(state), String(connectionId))
    return data
  },
  async pollDevice(connectionId: number, state: string, signal: AbortSignal): Promise<{ connected: boolean; interval: number }> {
    return (await api.post<{ connected: boolean; interval: number }>(`/connections/${connectionId}/oauth/device`, { state }, { signal })).data
  },
  async complete(query: URLSearchParams): Promise<void> {
    const state = query.get('state') ?? ''
    const connectionId = Number(sessionStorage.getItem(pendingKey(state))) || localConnection(state)
    if (!Number.isSafeInteger(connectionId) || connectionId <= 0) throw new Error('Missing OAuth session')
    try {
      await api.post(`/connections/${connectionId}/oauth/callback`, {
        state, code: query.get('code') ?? '', error: query.get('error') ?? '', iss: query.get('iss') ?? '',
      })
    } finally {
      sessionStorage.removeItem(pendingKey(state))
      localStorage.removeItem(localPendingPrefix + state)
    }
  },
  async disconnect(connectionId: number): Promise<void> {
    await api.delete(`/connections/${connectionId}/oauth`)
  },
}
