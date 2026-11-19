import api from '@/core/api'
import { isAxiosError } from 'axios'

export type PluginCompatibility = 'supported' | 'host_version' | 'untrusted_publisher' | 'unsupported_service' | 'native_publisher_required' | 'missing_dependency' | 'runtime_unconfigured' | 'revoked'
export type PluginAction = 'activate' | 'deactivate' | 'remove'

export interface LocalizedPluginText {
  en: string
  fr: string
}

interface PluginIdentity {
  code: string
  label: LocalizedPluginText
  version: string
  description: LocalizedPluginText
  contributions: {
    family: 'service_preset' | 'document_format' | 'llm_provider' | 'preview_converter' | 'data_template' | 'file_share_protocol'
    code: string
    label: LocalizedPluginText
    contract_version: number
  }[]
}

export interface PluginManifest extends PluginIdentity {
  minimum_galaris_version: string
  maximum_galaris_version_exclusive: string
  python_requirements?: string[]
  runtime_requirements?: { code: string; image: string }[]
}

export interface PluginPreview {
  manifest: PluginManifest
  digest: string
  signer: string
  compatibility: PluginCompatibility
  host_version: string
  host_identity: string
  can_force: boolean
}

export interface PluginRelease extends PluginPreview {
  installed: boolean
  selected: boolean
  active: boolean
  forced: boolean
}

export interface SampleRelease {
  source: 'development_sample'
  manifest: PluginIdentity
  active: boolean
  target: 'documents' | 'rest' | 'mcp'
  endpoint: string | null
}

export type PluginInventoryEntry = PluginRelease | SampleRelease

export interface PluginDetail {
  code: string
  releases: PluginInventoryEntry[]
  events: {
    version: string
    operation: 'installed' | 'activated' | 'deactivated' | 'removed' | 'activation_error' | 'revoked'
    occurred_at: string
    forced: boolean
  }[]
}

export function pluginErrorCode(error: unknown): string {
  if (!isAxiosError<{ detail: unknown }>(error)) return 'request_failed'
  const detail = error.response?.data?.detail
  return typeof detail === 'string' && /^[a-z_]{1,40}$/.test(detail) ? detail : 'request_failed'
}

function upload(file: File, preview?: PluginPreview, force = false) {
  const form = new FormData()
  form.append('file', file)
  if (preview) {
    form.append('digest', preview.digest)
    form.append('host_identity', preview.host_identity)
    form.append('force', String(force))
  }
  return form
}

export const pluginApi = {
  async list() {
    return (await api.get<PluginInventoryEntry[]>('/plugins')).data
  },
  async get(code: string) {
    return (await api.get<PluginDetail>(`/plugins/${encodeURIComponent(code)}`)).data
  },
  async catalogue() {
    return (await api.get<PluginPreview[]>('/plugins/catalog')).data
  },
  async catalogueFile(release: PluginPreview) {
    const { data } = await api.get<Blob>(`/plugins/catalog/${encodeURIComponent(release.digest)}`, { responseType: 'blob' })
    return new File([data], `${release.manifest.code}-${release.manifest.version}.zip`, { type: 'application/zip' })
  },
  async dataTemplate(plugin: string, template: string) {
    return (await api.get<Blob>(`/plugins/${encodeURIComponent(plugin)}/templates/${encodeURIComponent(template)}`,
      { responseType: 'blob' })).data
  },
  async preview(file: File) {
    return (await api.post<PluginPreview>('/plugins/preview', upload(file))).data
  },
  async install(file: File, preview: PluginPreview, force: boolean) {
    return (await api.post<PluginRelease>('/plugins/install', upload(file, preview, force))).data
  },
  async change(release: PluginInventoryEntry, action: PluginAction) {
    const { code, version } = release.manifest
    return (await api.post<PluginInventoryEntry>(
      `/plugins/${encodeURIComponent(code)}/${encodeURIComponent(version)}/${action}`,
      'host_identity' in release ? { host_identity: release.host_identity } : { source: release.source },
    )).data
  },
}
