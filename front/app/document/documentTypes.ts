import { defineAsyncComponent } from 'vue'
import type { DocumentType } from './types'
import type { preparePortableDocumentSnapshot } from '@/core/util/facade'

type SnapshotArguments = Parameters<typeof preparePortableDocumentSnapshot>

const text = {
  code: 'text', icon: 'description', label: 'documents.types.text',
  editor: defineAsyncComponent(async () => (await import('./text')).TextContentEditor),
  snapshot: async (...args: SnapshotArguments) => (await import('./text')).previewSnapshot(...args),
} as const
const data = {
  code: 'data', icon: 'data_object', label: 'documents.types.data',
  editor: defineAsyncComponent(async () => (await import('./data')).DataContentEditor),
  snapshot: async (...args: SnapshotArguments) => (await import('./data')).previewSnapshot(...args),
} as const
export const documentTypes = [text, data]
export type DocumentKind = typeof documentTypes[number]['code']
export function documentType(type?: DocumentType): typeof text | typeof data {
  return type === 'data' || type === 'dataset' ? data : text
}
