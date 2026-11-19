import type { PluginInventoryEntry, PluginRelease, SampleRelease } from './services/pluginApi'

const capabilityAppearance = {
  service_preset: { icon: 'hub', tone: 'cyan' },
  document_format: { icon: 'description', tone: 'iris' },
  llm_provider: { icon: 'smart_toy', tone: 'violet' },
  preview_converter: { icon: 'preview', tone: 'green' },
  data_template: { icon: 'data_object', tone: 'orange' },
  file_share_protocol: { icon: 'folder', tone: 'cyan' },
} as const

const sampleAppearance = {
  documents: { icon: 'draw', tone: 'iris' },
  rest: { icon: 'http', tone: 'cyan' },
  mcp: { icon: 'hub', tone: 'blue' },
} as const

export function isDevelopmentSample(release: PluginInventoryEntry): release is SampleRelease {
  return 'source' in release && release.source === 'development_sample'
}

export function pluginAppearance(release: PluginInventoryEntry) {
  if (isDevelopmentSample(release)) return sampleAppearance[release.target]
  const [first, ...others] = release.manifest.contributions
  return first && others.every(item => item.family === first.family)
    ? capabilityAppearance[first.family]
    : { icon: 'extension', tone: 'blue' } as const
}

export function canActivateRelease(release: PluginRelease): boolean {
  return release.installed && (release.compatibility === 'supported' || (release.can_force && release.forced))
}

export function releaseState(release: PluginInventoryEntry) {
  if (release.active) return 'active'
  if (isDevelopmentSample(release)) return 'inactive'
  if (release.selected) return 'blocked'
  return release.installed ? 'inactive' : 'removed'
}
