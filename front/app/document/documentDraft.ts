import type { DocumentGlobalAccess } from './types'

export interface DocumentDraft {
  owner: string
  title: string
  content: string
  keywords: string[]
  globalAccess: DocumentGlobalAccess
  sharing: Record<number, 'none' | 'read' | 'edit'>
}

export function sameDocumentDraft(left: DocumentDraft | null, right: DocumentDraft | null): boolean {
  return left !== null && right !== null && left.owner === right.owner && left.title === right.title
    && left.content === right.content && left.globalAccess === right.globalAccess
    && left.keywords.length === right.keywords.length && left.keywords.every((value, index) => value === right.keywords[index])
    && Object.keys(left.sharing).length === Object.keys(right.sharing).length
    && Object.entries(left.sharing).every(([id, access]) => access === right.sharing[Number(id)])
}

export function documentDraftKey(userId: number, agentId: number | null, documentId: string): string {
  return `galaris:document-draft:user:${userId}:${agentId}:${documentId}`
}

interface SavedDraft { revision?: number; base: DocumentDraft; draft: DocumentDraft; user_id?: number }

function isDraft(value: unknown): value is DocumentDraft {
  if (!value || typeof value !== 'object') return false
  const draft = value as Partial<DocumentDraft>
  return typeof draft.owner === 'string' && typeof draft.title === 'string' && typeof draft.content === 'string'
    && Array.isArray(draft.keywords) && draft.keywords.every(value => typeof value === 'string')
    && [0, 1, 2].includes(draft.globalAccess ?? -1)
    && !!draft.sharing && typeof draft.sharing === 'object' && !Array.isArray(draft.sharing)
    && Object.entries(draft.sharing).every(([id, access]) => /^\d+$/.test(id) && ['none', 'read', 'edit'].includes(access))
}

/** Unattributed old drafts are retained, never assigned to whichever account opens next. */
export function restoreDocumentDraft(storage: Storage, userId: number, agentId: number | null, documentId: string): SavedDraft | null {
  const key = documentDraftKey(userId, agentId, documentId)
  const legacyKey = `galaris:document-draft:${agentId}:${documentId}`
  const scoped = storage.getItem(key)
  const raw = scoped ?? storage.getItem(legacyKey)
  if (!raw) return null
  const saved = JSON.parse(raw) as Partial<SavedDraft> | null
  if (!saved || (!scoped && saved.user_id !== userId) || (saved.user_id !== undefined && saved.user_id !== userId)
    || !isDraft(saved.base) || !isDraft(saved.draft)) return null
  if (!scoped) {
    storage.setItem(key, raw)
    storage.removeItem(legacyKey)
  }
  return { ...saved, base: saved.base, draft: saved.draft }
}
