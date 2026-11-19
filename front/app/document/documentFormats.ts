import { defineAsyncComponent, markRaw, shallowReactive } from 'vue'
import type { Component } from 'vue'
import type { DocumentFocusAnchor } from '@/core/util'
import type { RenderedDocumentResolver } from '@/core/util/facade'
import type { pluginHost } from './pluginHost'
import { registerFormat } from './formatRegistry'
import type { DocumentFormatDescriptor } from './formatRegistry'
import { parseMindMap } from './mindmap/model'

export type { DocumentFormatDescriptor, DocumentFormatCode } from './formatRegistry'
export type DocumentCreationMode = string
type Snapshot = (
  content: string, title: string, signal: AbortSignal,
  resolveImage?: (documentId: string, attachmentId: string) => Promise<Blob>,
  resolveRenderedContent?: RenderedDocumentResolver, source?: DocumentContentSource,
) => Promise<string>
export interface DocumentExchangeExport {
  code: string
  extension: string
  label: string
}
export interface DocumentContentSource {
  key: string
  revision: number
  readonly: boolean
  load: (signal: AbortSignal) => Promise<Blob>
  save: (content: Blob, expectedRevision: number, signal: AbortSignal) => Promise<number>
}
export interface DocumentFormatEditorHandle {
  insertResource?: (html: string) => void
  commitDraft?: () => void
  flush?: () => Promise<boolean>
  discardDraft?: () => Promise<void> | void
  captureFocus?: () => DocumentFocusAnchor | null
}
export interface DocumentFormatContribution {
  code: string
  version: number
  provider: string
  icon: string
  label: string
  localizedLabel?: { fr: string; en: string }
  editor: Component
  snapshot: Snapshot
  validateDraft: (source: string) => boolean
  embed?: Component
  preview?: Component
  storageKind?: 'text' | 'file'
  nativeExtension?: string
  exchangeExports?: readonly DocumentExchangeExport[]
}

const contributions = new Map<string, DocumentFormatContribution>()
const bundled = new Map<string, { url: string; contribution: DocumentFormatContribution }>()
export const documentFormats = shallowReactive<DocumentFormatContribution[]>([])
export const documentFormatCatalogue = shallowReactive<DocumentFormatDescriptor[]>([])
let catalogueLoaded = false

function refresh(): void {
  documentFormats.splice(0, documentFormats.length, ...[...contributions.values(), ...Array.from(bundled.values(), value => value.contribution)].filter(value =>
    !catalogueLoaded || documentFormatCatalogue.some(server => server.code === value.code && server.version === value.version && server.provider === value.provider)))
}
/** Native modules and the future effective plugin loader use the same port. */
export function registerDocumentFormat(contribution: DocumentFormatContribution): void {
  registerFormat(contributions, { ...contribution, editor: markRaw(contribution.editor),
    preview: contribution.preview ? markRaw(contribution.preview) : undefined,
    embed: contribution.embed ? markRaw(contribution.embed) : undefined })
  refresh()
}
export function setDocumentFormatCatalogue(catalogue: DocumentFormatDescriptor[]): void {
  documentFormatCatalogue.splice(0, documentFormatCatalogue.length, ...catalogue)
  catalogueLoaded = true
  const current = new Set<string>()
  for (const descriptor of catalogue) {
    const url = descriptor.plugin_editor?.module_url
    if (!url || descriptor.storage_kind !== 'file' || contributions.has(descriptor.code)
      || !/^\/api\/plugins\/assets\/[a-f0-9]{64}\/[a-z0-9.-]+\.mjs$/.test(url)) continue
    current.add(descriptor.code)
    if (bundled.get(descriptor.code)?.url !== url) {
      bundled.set(descriptor.code, { url, contribution: bundledFormat(descriptor, url) })
    }
  }
  for (const code of bundled.keys()) if (!current.has(code)) bundled.delete(code)
  refresh()
}
export function findDocumentFormat(code = 'text', version?: number): DocumentFormatContribution | undefined {
  const contribution = contributions.get(code) ?? bundled.get(code)?.contribution
  if (!contribution || (version !== undefined && version !== contribution.version)) return undefined
  if (catalogueLoaded && !documentFormatCatalogue.some(server => server.code === contribution.code
    && server.version === contribution.version && server.provider === contribution.provider)) return undefined
  return contribution
}
const fallback: DocumentFormatContribution = {
  code: 'unavailable', version: 1, provider: 'galaris', icon: 'insert_drive_file', label: 'documents.formatUnavailable',
  editor: defineAsyncComponent(() => import('./components/UnavailableDocumentFormat.vue')),
  snapshot: async source => `<pre>${source.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')}</pre>`,
  validateDraft: () => false,
}

export function formatDisplayLabel(format: DocumentFormatContribution, translate: (key: string) => string, locale: string): string {
  return format.localizedLabel?.[locale === 'fr' ? 'fr' : 'en'] ?? translate(format.label)
}

type PluginPresentation = Pick<DocumentFormatContribution, 'editor' | 'preview' | 'embed' | 'snapshot'>

function bundledFormat(descriptor: DocumentFormatDescriptor, url: string): DocumentFormatContribution {
  let loading: Promise<PluginPresentation> | undefined
  function load(): Promise<PluginPresentation> {
    loading ??= Promise.all([
      import('./pluginHost'),
      import(/* @vite-ignore */ url) as Promise<{ createFormat: (host: typeof pluginHost) => PluginPresentation }>,
    ]).then(([host, module]) => module.createFormat(host.pluginHost)).catch(error => { loading = undefined; throw error })
    return loading
  }
  return {
    code: descriptor.code, provider: descriptor.provider, version: descriptor.version,
    icon: descriptor.icon, label: 'documents.formatUnavailable', localizedLabel: descriptor.plugin_editor?.label,
    storageKind: 'file', nativeExtension: descriptor.import_extensions[0], validateDraft: () => true,
    editor: markRaw(defineAsyncComponent({ loader: async () => (await load()).editor, errorComponent: fallback.editor })),
    preview: markRaw(defineAsyncComponent({ loader: async () => (await load()).preview ?? fallback.editor, errorComponent: fallback.editor })),
    embed: descriptor.capabilities.embed === 'native' ? markRaw(defineAsyncComponent({ loader: async () => (await load()).embed ?? fallback.editor, errorComponent: fallback.editor })) : undefined,
    snapshot: async (...args) => (await load()).snapshot(...args),
  }
}
export function documentFormat(code?: string, version?: number): DocumentFormatContribution {
  return findDocumentFormat(code, version) ?? fallback
}
const documentReferenceContent = defineAsyncComponent(() => import('./components/DocumentReferenceContent.vue'))
registerDocumentFormat({
  code: 'text', version: 1, provider: 'galaris', icon: 'description', label: 'documents.formats.text',
  editor: defineAsyncComponent(async () => (await import('./text')).TextContentEditor),
  preview: defineAsyncComponent(async () => (await import('@/core/util')).EditorialContent),
  embed: defineAsyncComponent(() => import('./components/DocumentTextEmbed.vue')),
  snapshot: async (source, title, signal, images, rendered) => (await import('./text')).previewSnapshot(source, title, signal, images, rendered), validateDraft: () => true,
})
registerDocumentFormat({
  code: 'data', version: 1, provider: 'galaris', icon: 'data_object', label: 'documents.formats.data',
  editor: defineAsyncComponent(async () => (await import('./data')).DataContentEditor),
  preview: defineAsyncComponent(async () => (await import('./data')).DataContentEditor),
  snapshot: async (source, title, signal, images, rendered) => (await import('./data')).previewSnapshot(source, title, signal, images, rendered),
  validateDraft: source => { try { JSON.parse(source); return true } catch { return false } },
})
const mindMapEditor = defineAsyncComponent(() => import('./mindmap/MindMapEditor.vue'))
registerDocumentFormat({
  code: 'mindmap', version: 1, provider: 'galaris', icon: 'account_tree', label: 'documents.formats.mindmap',
  editor: mindMapEditor, preview: mindMapEditor, embed: documentReferenceContent, nativeExtension: '.mindmap',
  exchangeExports: [
    { code: 'freeplane', extension: '.mm', label: 'Freeplane (.mm)' },
    { code: 'freemind', extension: '.mm', label: 'FreeMind (.mm)' },
    { code: 'opml', extension: '.opml', label: 'OPML (.opml)' },
    { code: 'xmind', extension: '.xmind', label: 'XMind (.xmind)' },
  ],
  snapshot: async (source, title, signal, images) => (await import('./mindmap/content')).mindMapSnapshot(source, title, signal, images),
  validateDraft: source => !!parseMindMap(source),
})
