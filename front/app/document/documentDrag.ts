import type { DocumentLibraryEntry } from './types'

/** Keep rendered order and carry selected descendants with their selected parent. */
export function documentDragSelection(id: string, selected: string[], ordered: DocumentLibraryEntry[], known: DocumentLibraryEntry[]): DocumentLibraryEntry[] {
  const ids = new Set(selected.includes(id) ? selected : [id])
  const entries = new Map([...ordered, ...known].map(entry => [entry.item.id, entry]))
  const candidates = [...new Set([...ordered.map(entry => entry.item.id), ...ids])].filter(value => ids.has(value))
  return candidates.flatMap(value => {
    const entry = entries.get(value)
    let parent = entry?.parent_document_id
    const seen = new Set([value])
    while (parent && !seen.has(parent)) {
      if (ids.has(parent)) return []
      seen.add(parent); parent = entries.get(parent)?.parent_document_id
    }
    return entry ? [entry] : []
  })
}

export function setDocumentDragData(event: DragEvent, entries: DocumentLibraryEntry[]): void {
  if (!event.dataTransfer) return
  const links = entries.map(entry => {
    const link = document.createElement('a')
    link.href = `document://${entry.item.id}`; link.textContent = entry.item.title
    return link
  })
  event.dataTransfer.setData('text/html', links.map(link => link.outerHTML).join('<br>'))
  event.dataTransfer.setData('text/plain', links.map(link => link.href).join('\n'))
  event.dataTransfer.setData('text/uri-list', links.map(link => link.href).join('\r\n'))
  event.dataTransfer.effectAllowed = 'copyMove'
}
