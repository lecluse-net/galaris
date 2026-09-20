import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface ExecutorUser {
  agent_id: number
  code: string
  uid: number
  enabled: boolean
  home: string
  usage_bytes: number
  updated_at?: number
}

export interface ExecutorSession {
  agent_id: number
  code: string
  run_id: string
  pid: number
  running: boolean
  command: string
  cwd: string
  started_at?: number
  task_id?: string | null
}

export interface ExecutorStatus {
  version: string
  ssh_host_key: string
  uptime_s: number
  ssh: string
  disk: { total: number; used: number; free: number }
  load_average: number[]
  users: ExecutorUser[]
  active_users: number
  disabled_users: number
  sessions: ExecutorSession[]
  active_sessions: number
  resources: {
    memory_current: number | null
    memory_limit: number | null
    pids_current: number
    pids_limit: number | null
    cpu_usage_usec: number | null
  }
}

export interface ExecutorResponse<T = Record<string, unknown>> {
  ok: boolean
  result: T
  error: string
}

export interface ExecutorAvailability {
  in_use: boolean
}

export interface EmbeddedProvisionResult {
  connection_id: number
  agent_id: number
  agent_code: string
  public_key: string
  status: {
    reachable: boolean
    authenticated: boolean
    host_key_verified: boolean
    home_writable: boolean
    sftp_available: boolean
    mode: string
    error?: string
  }
}

export interface ConsoleConnectionStatus {
  reachable: boolean
  authenticated: boolean
  host_key_verified: boolean
  home?: string
  home_writable: boolean
  sftp_available: boolean
  galaris_exec_available?: boolean
  operation_recovery_available?: boolean
  mode: string
  detected_commands?: string[]
  error?: string
}

export interface ConsoleConnectionTestResult {
  connection_id: number
  status: ConsoleConnectionStatus
}

export interface ConsoleHelperInstallResult {
  connection_id: number
  path: string
  version: string
  status: ConsoleConnectionStatus
}

export const consoleService = {
  availability(): Promise<AxiosResponse<ExecutorAvailability>> {
    return api.get('/console/executor/availability')
  },
  status(): Promise<AxiosResponse<ExecutorResponse<ExecutorStatus>>> {
    return api.get('/console/executor/status')
  },
  action<T = Record<string, unknown>>(
    operation: string,
    payload: Record<string, unknown> = {},
  ): Promise<AxiosResponse<ExecutorResponse<T>>> {
    return api.post('/console/executor/action', { operation, payload })
  },
  provision(agentId: number): Promise<AxiosResponse<EmbeddedProvisionResult>> {
    return api.post('/console/embedded/provision', { agent_id: agentId })
  },
  generateKey(connectionId: number): Promise<AxiosResponse<{ connection_id: number; public_key: string }>> {
    return api.post(`/console/connections/${connectionId}/generate-key`)
  },
  testConnection(connectionId: number): Promise<AxiosResponse<ConsoleConnectionTestResult>> {
    return api.post(`/console/connections/${connectionId}/test`)
  },
  installHelper(connectionId: number): Promise<AxiosResponse<ConsoleHelperInstallResult>> {
    return api.post(`/console/connections/${connectionId}/install-helper`)
  },
  scanHostKey(host: string, port: number): Promise<AxiosResponse<{ host: string; port: number; key: string; fingerprint: string }>> {
    return api.post('/console/host-key/scan', { host, port })
  },
}
