import { shallowRef } from 'vue'
import { documentIdFromResourceUri, documentUriFromLink } from './documentResource'

/** Render-only hosts: document icons never become part of the authored HTML. */
export function useDocumentLinkIcons() {
  const targets = shallowRef<Array<{ key: number; element: HTMLElement; documentId: string }>>([])
  let sequence = 0
  function mount(element: HTMLElement, documentId: string): () => void {
    const target = { key: ++sequence, element, documentId }
    let disposed = false
    queueMicrotask(() => { if (!disposed) targets.value = [...targets.value, target] })
    return () => { disposed = true; targets.value = targets.value.filter(item => item.key !== target.key) }
  }
  function decorate(link: HTMLAnchorElement): () => void {
    const uri = documentUriFromLink(link.dataset.richReference ?? link.getAttribute('href') ?? '', window.location.origin)
    const id = uri && documentIdFromResourceUri(uri)
    if (!id) return () => {}
    const element = link.ownerDocument.createElement('span')
    element.className = 'document-link-icon'
    element.contentEditable = 'false'
    element.setAttribute('aria-hidden', 'true')
    link.prepend(element)
    const dispose = mount(element, id)
    return () => { dispose(); element.remove() }
  }
  return { targets, mount, decorate }
}
