/** Pure contribution registry, also usable by plugin qualification runners. */
export type DocumentFormatCode = string
export type FormatCapability = 'editor' | 'preview' | 'embed' | 'thumbnail' | 'pdf' | 'native_export' | 'import'
export type CapabilitySupport = 'native' | 'fallback' | 'unavailable'
export interface DocumentFormatDescriptor {
  code: string
  version: number
  contract_version: number
  provider: string
  media_type: string
  storage_kind: 'text' | 'file'
  icon: string
  capabilities: Record<FormatCapability, CapabilitySupport>
  capability_complete: boolean
  qualification: 'not_run'
  import_extensions: string[]
}
export function registerFormat<T extends { code: string; version: number; provider: string }>(registry: Map<string, T>, contribution: T): void {
  if (!/^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$/.test(contribution.code) || contribution.code.length > 80
    || !Number.isSafeInteger(contribution.version) || contribution.version < 1 || !contribution.provider) throw new Error('Invalid document format contribution')
  if (['html', 'form', 'dataset', 'process'].includes(contribution.code) || registry.has(contribution.code)) throw new Error('Duplicate or reserved document format')
  registry.set(contribution.code, contribution)
}
