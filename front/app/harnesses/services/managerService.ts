import api from '@/core/api'

export type ManagerState = 'ok' | 'missing_secret' | 'invalid_secret' | 'invalid_url'
  | 'dns_error' | 'connection_error' | 'timeout' | 'tls_error' | 'unauthorized'
  | 'forbidden' | 'not_found' | 'http_error' | 'incompatible_manager' | 'invalid_response'

export interface ManagerDiagnostics {
  state: ManagerState
  manager_url: string
  galaris_api_url: string
  public_api_url: string
  secret_configured: boolean
  api_url_source: 'HARNESS_MANAGER_GALARIS_API_URL' | 'APP_HOST'
  mode_hint: 'local' | 'remote' | 'unknown'
  api_issue: 'none' | 'missing' | 'invalid_url' | 'loopback' | 'docker_hostname'
  runtime_api_check: 'not_checked'
  legacy_environment_detected: boolean
  http_status: number | null
  manager_version: string | null
  expected_version: string | null
  version_status: 'not_checked' | 'current' | 'update_available' | 'newer' | 'unknown'
}

export const managerService = {
  async release(): Promise<ManagerRelease> {
    return (await api.get<ManagerRelease>('/harness-manager/release')).data
  },
  async archive(): Promise<Blob> {
    return (await api.get<Blob>('/harness-manager/release.zip', { responseType: 'blob' })).data
  },
  async installation(data: ManagerHostSetup): Promise<Blob> {
    return (await api.post<Blob>('/harness-manager/installation.zip', data, { responseType: 'blob' })).data
  },
  async configuration(): Promise<ManagerConfiguration> {
    return (await api.get<ManagerConfiguration>('/harness-manager/configuration')).data
  },
  async save(data: ManagerConfigurationUpdate): Promise<ManagerConfiguration> {
    return (await api.put<ManagerConfiguration>('/harness-manager/configuration', data)).data
  },
  async generateSecret(): Promise<string> {
    return (await api.post<{ secret: string }>('/harness-manager/generate-secret')).data.secret
  },
  async environment(data: ManagerHostSetup): Promise<string> {
    return (await api.post<string>('/harness-manager/environment', data, { responseType: 'text' })).data
  },
  async diagnostics(): Promise<ManagerDiagnostics> {
    return (await api.get<ManagerDiagnostics>('/harness-manager/diagnostics')).data
  },
}

export interface ManagerConfiguration {
  manager_url: string
  galaris_api_url: string
  secret_configured: boolean
}
export interface ManagerConfigurationUpdate {
  manager_url: string
  galaris_api_url: string
  secret?: string
}
export interface ManagerHostSetup {
  update_url?: string
  api_host: string
  api_port: number
  allowed_ip: string
  base_dir: string
  ignore_dirs: string
  max_file_size_mb: number
  max_raw_file_size_mb: number
}

export interface ManagerRelease {
  version: string
  sha256: string
  size: number
  update_url: string
}
