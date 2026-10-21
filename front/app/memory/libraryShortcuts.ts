import type { LibraryShortcuts } from '@/core/util/interface'
export { vLibraryShortcuts, type LibraryShortcuts } from '@/core/util/interface'
import type { DocumentLibraryEntry } from './types'
export type DocumentRowAction = 'rename' | 'delete'
export function documentRowShortcuts(entry: DocumentLibraryEntry, busy: boolean, open: () => void, create: () => void, action: (value: DocumentRowAction) => void): LibraryShortcuts {
  if (busy) return {}
  const editable = entry.item.access.can_write && !entry.item.read_only && !entry.item.source_managed
  return {
    F3: create, F4: open, F7: create,
    ...(editable ? { F2: () => action('rename') } : {}),
    ...(editable && !entry.item.deletion_protected ? { Delete: () => action('delete') } : {}),
  }
}
