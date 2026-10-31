import { ref } from 'vue'

export interface DocumentSelectionItem { key: string; id: string }
type Modifiers = Pick<MouseEvent, 'ctrlKey' | 'metaKey' | 'shiftKey'>

export function documentSelectionModifiers(event?: Event): Modifiers | undefined {
  return event instanceof MouseEvent || event instanceof KeyboardEvent ? event : undefined
}

/** Selection follows rendered occurrences, while documents are selected only once. */
export function useDocumentSelection() {
  const selected = ref<string[]>([])
  const anchors = new Map<string, string>()

  function clear(): void { selected.value = []; anchors.clear() }

  function select(scope: string, key: string, items: DocumentSelectionItem[], input?: Event, toggle = false): void {
    const event = documentSelectionModifiers(input)
    const index = items.findIndex(item => item.key === key)
    const item = items[index]
    if (!item) return
    const additive = Boolean(event?.ctrlKey || event?.metaKey)
    if (event?.shiftKey) {
      const anchor = items.findIndex(value => value.key === anchors.get(scope))
      const start = anchor < 0 ? index : anchor
      const range = items.slice(Math.min(start, index), Math.max(start, index) + 1).map(value => value.id)
      selected.value = [...new Set(additive ? [...selected.value, ...range] : range)]
      if (anchor < 0) anchors.set(scope, key)
    } else {
      selected.value = additive || toggle
        ? selected.value.includes(item.id) ? selected.value.filter(id => id !== item.id) : [...selected.value, item.id]
        : [item.id]
      anchors.set(scope, key)
    }
  }

  return { selected, select, clear }
}
