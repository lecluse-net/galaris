import { defineAsyncComponent, markRaw, shallowReactive } from 'vue'
import type { Component } from 'vue'
import type { preparePortableDocumentSnapshot } from '@/core/util/facade'
import { registerFormat } from './formatRegistry'
import type { DocumentFormatDescriptor } from './formatRegistry'

export type { DocumentFormatDescriptor, DocumentFormatCode } from './formatRegistry'
export type DocumentCreationMode = string
type Snapshot = (...args: [...Parameters<typeof preparePortableDocumentSnapshot>, DocumentContentSource?]) => Promise<string>
export interface DocumentContentSource {
  key: string
  revision: number
  readonly: boolean
  load: (signal: AbortSignal) => Promise<Blob>
  save: (content: Blob, expectedRevision: number, signal: AbortSignal) => Promise<number>
}
export interface DocumentFormatEditorHandle {
  insertResource?: (html: string) => void
  flush?: () => Promise<boolean>
  discardDraft?: () => Promise<void> | void
}
export interface DocumentFormatContribution {
  code: string
  version: number
  provider: string
  icon: string
  label: string
  editor: Component
  snapshot: Snapshot
  validateDraft: (source: string) => boolean
  embed?: Component
  preview?: Component
  storageKind?: 'text' | 'file'
}

const contributions = new Map<string, DocumentFormatContribution>()
export const documentFormats = shallowReactive<DocumentFormatContribution[]>([])
export const documentFormatCatalogue = shallowReactive<DocumentFormatDescriptor[]>([])
let catalogueLoaded = false

function refresh(): void {
  documentFormats.splice(0, documentFormats.length, ...[...contributions.values()].filter(value =>
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
  refresh()
}
export function findDocumentFormat(code = 'text', version?: number): DocumentFormatContribution | undefined {
  const contribution = contributions.get(code)
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
export function documentFormat(code?: string, version?: number): DocumentFormatContribution {
  return findDocumentFormat(code, version) ?? fallback
}
registerDocumentFormat({
  code: 'text', version: 1, provider: 'galaris', icon: 'description', label: 'documents.formats.text',
  editor: defineAsyncComponent(async () => (await import('./text')).TextContentEditor),
  preview: defineAsyncComponent(async () => (await import('@/core/util')).EditorialContent),
  snapshot: async (source, title, signal, images, rendered) => (await import('./text')).previewSnapshot(source, title, signal, images, rendered), validateDraft: () => true,
})
registerDocumentFormat({
  code: 'data', version: 1, provider: 'galaris', icon: 'data_object', label: 'documents.formats.data',
  editor: defineAsyncComponent(async () => (await import('./data')).DataContentEditor),
  preview: defineAsyncComponent(async () => (await import('./data')).DataContentEditor),
  snapshot: async (source, title, signal, images, rendered) => (await import('./data')).previewSnapshot(source, title, signal, images, rendered),
  validateDraft: source => { try { JSON.parse(source); return true } catch { return false } },
})
