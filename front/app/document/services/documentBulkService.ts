import { documentService } from './documentService'
import type { DocumentLibraryEntry, DocumentOwnerKind, DocumentSharingUpdate } from '../types'

export type DocumentBulkOperation =
  | { kind: 'delete' }
  | { kind: 'keywords'; remove: boolean; values: string[] }
  | { kind: 'owner'; ownerKind: DocumentOwnerKind; ownerId: number }
  | { kind: 'sharing'; recipient: { kind: DocumentSharingUpdate['kind']; id: number } | null; access: 'read' | 'write' | 'remove' }

export function documentEntryActor(entry: DocumentLibraryEntry): number | null {
  if (entry.user_access?.can_write) return null
  if (entry.item.owner_agent_id !== null && entry.writable_agent_ids.includes(entry.item.owner_agent_id)) return entry.item.owner_agent_id
  return entry.writable_agent_ids[0] ?? entry.agent_ids[0] ?? null
}

/** Apply a command to one resource using its current version, never another row's settings. */
export async function applyDocumentBulkOperation(entry: DocumentLibraryEntry, operation: DocumentBulkOperation, active: () => boolean): Promise<void> {
  const id = entry.item.id
  if (operation.kind === 'sharing') {
    const state = await documentService.documentSharing(id)
    if (!active()) return
    if (!state.can_manage) throw new Error('permission')
    const target = operation.recipient
    if (target) {
      // Ownership is intrinsic and cannot be revoked through a sharing command.
      if (state.owner?.kind === target.kind && state.owner.id === target.id) return
      if (operation.access === 'remove' && !state.grants.some(grant => grant.kind === target.kind && grant.id === target.id)) return
      await documentService.updateDocumentSharing(id, {
        ...target, can_write: operation.access === 'remove' ? null : operation.access === 'write',
        expected_lock_version: state.lock_version,
      })
    } else {
      await documentService.updateDocumentSharingLevel(id, {
        level: operation.access === 'remove' ? (state.grants.some(grant => grant.kind === 'team') ? 'groups' : 'private') : 'public',
        can_write: operation.access === 'write',
        // Preserve all explicit grants even when changing public access.
        grants: state.grants.map(({ kind, id, can_write }) => ({ kind, id, can_write })),
        expected_lock_version: state.lock_version,
      })
    }
    return
  }
  if (operation.kind === 'delete') {
    if (active()) await documentService.deleteDocument(id, documentEntryActor(entry))
    return
  }
  const { item } = await documentService.getManagedDocument(id)
  if (!active()) return
  if (operation.kind === 'owner') {
    await documentService.changeDocumentOwner(id, item.revision, item.lock_version, operation.ownerKind, operation.ownerId)
  } else {
    const values = operation.values.map(value => value.trim()).filter(Boolean)
    const normalized = new Set(values.map(value => value.toLowerCase()))
    const keywords = operation.remove
      ? item.keywords.filter(value => !normalized.has(value.toLowerCase()))
      : [...item.keywords]
    if (!operation.remove) {
      const existing = new Set(item.keywords.map(value => value.toLowerCase()))
      for (const value of values) {
        if (!existing.has(value.toLowerCase())) { keywords.push(value); existing.add(value.toLowerCase()) }
      }
    }
    if (keywords.length > 50 || values.some(value => value.length > 100)) throw new Error('keywordLimit')
    await documentService.updateDocument(id, documentEntryActor(entry), {
      expected_revision: item.revision, expected_lock_version: item.lock_version, keywords,
    })
  }
}
