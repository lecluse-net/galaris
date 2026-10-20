import type { ObjectDirective } from 'vue'
import type { DocumentLibraryEntry } from './types'

export type DocumentRowAction = 'rename' | 'delete'
type ShortcutKey = 'F2' | 'F3' | 'F4' | 'F7' | 'Delete'
export type LibraryShortcuts = Partial<Record<ShortcutKey, () => void>>
const rows = new Map<HTMLElement, LibraryShortcuts>()
const shortcutKeys = new Set(['F2', 'F3', 'F4', 'F7', 'Delete'])
const rowSelector = '[data-library-shortcut-row]'
const editingSelector = 'input, textarea, select, [role="textbox"], [role="combobox"], [contenteditable]:not([contenteditable="false"])'

export function documentRowShortcuts(entry: DocumentLibraryEntry, busy: boolean, open: () => void, create: () => void, action: (value: DocumentRowAction) => void): LibraryShortcuts {
  if (busy) return {}
  const editable = entry.item.access.can_write && !entry.item.read_only && !entry.item.source_managed
  return {
    F3: create, F4: open, F7: create,
    ...(editable ? { F2: () => action('rename') } : {}),
    ...(editable && !entry.item.deletion_protected ? { Delete: () => action('delete') } : {}),
  }
}

function dispatch(event: KeyboardEvent): void {
  if (!shortcutKeys.has(event.key) || event.defaultPrevented || event.repeat || event.isComposing || event.ctrlKey || event.altKey || event.metaKey || event.shiftKey) return
  if (!(event.target instanceof Element) || event.target.closest(editingSelector)) return
  if (document.activeElement?.closest(editingSelector) || document.querySelector('.q-dialog, .q-menu')) return
  const focused = event.target.closest(rowSelector)
    ?? event.target.closest('[role="treeitem"]')?.querySelector(rowSelector)
  const hovered = document.querySelector(`${rowSelector}:hover`)
  const row = hovered ?? focused
  if (!(row instanceof HTMLElement)) return
  const action = rows.get(row)?.[event.key as ShortcutKey]
  if (!action) return
  event.preventDefault()
  event.stopPropagation()
  action()
}

/** One dispatcher for all rendered rows, removed when the library leaves the page. */
export const vLibraryShortcuts: ObjectDirective<HTMLElement, LibraryShortcuts> = {
  mounted(element, binding) {
    if (!rows.size) window.addEventListener('keydown', dispatch)
    element.setAttribute('data-library-shortcut-row', '')
    rows.set(element, binding.value)
  },
  updated(element, binding) { rows.set(element, binding.value) },
  unmounted(element) {
    rows.delete(element)
    if (!rows.size) window.removeEventListener('keydown', dispatch)
  },
}
