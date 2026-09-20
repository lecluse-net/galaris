const DOCUMENT_ID_SOURCE = '[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}'
const DOCUMENT_ID_PATTERN = new RegExp(`^${DOCUMENT_ID_SOURCE}$`, 'i')
const DOCUMENT_RESOURCE_PATTERN = new RegExp(`^document://(${DOCUMENT_ID_SOURCE})$`, 'i')
const DOCUMENT_RESOURCE_GLOBAL_PATTERN = new RegExp(`document://(${DOCUMENT_ID_SOURCE})`, 'gi')

function normalizeDocumentId(value: string): string | null {
  const candidate = value.trim()
  return DOCUMENT_ID_PATTERN.test(candidate) ? candidate.toLowerCase() : null
}

export function documentIdFromResourceUri(value: string): string | null {
  const match = DOCUMENT_RESOURCE_PATTERN.exec(value.trim())
  return match?.[1]?.toLowerCase() ?? null
}

export function documentIdFromRouteQuery(value: unknown): string | null {
  const candidate = Array.isArray(value) ? value[0] : value
  return typeof candidate === 'string' ? normalizeDocumentId(candidate) : null
}

export function documentResourceHref(documentId: string): string {
  const normalized = normalizeDocumentId(documentId)
  return normalized
    ? `/memory/documents?document_id=${encodeURIComponent(normalized)}`
    : '/memory/documents'
}

function markDocumentLink(link: HTMLAnchorElement, documentId: string): void {
  link.setAttribute('href', documentResourceHref(documentId))
  link.dataset.documentResourceId = documentId
}

/** Convert document resource URIs in safe rendered HTML to internal application links. */
export function linkDocumentResourceUris(html: string): string {
  const parsedDocument = new DOMParser().parseFromString(html, 'text/html')

  parsedDocument.body.querySelectorAll<HTMLAnchorElement>('a[href]').forEach(link => {
    const documentId = documentIdFromResourceUri(link.getAttribute('href') ?? '')
    if (documentId) markDocumentLink(link, documentId)
  })

  const walker = parsedDocument.createTreeWalker(parsedDocument.body, NodeFilter.SHOW_TEXT)
  const textNodes: Text[] = []
  let currentNode = walker.nextNode()
  while (currentNode) {
    if (currentNode instanceof Text && !currentNode.parentElement?.closest('a')) {
      textNodes.push(currentNode)
    }
    currentNode = walker.nextNode()
  }

  for (const textNode of textNodes) {
    const matches = [...textNode.data.matchAll(DOCUMENT_RESOURCE_GLOBAL_PATTERN)]
    if (matches.length === 0) continue

    const fragment = parsedDocument.createDocumentFragment()
    let cursor = 0
    for (const match of matches) {
      const documentId = match[1]?.toLowerCase()
      if (!documentId) continue
      fragment.append(textNode.data.slice(cursor, match.index))
      const link = parsedDocument.createElement('a')
      link.textContent = match[0]
      markDocumentLink(link, documentId)
      fragment.append(link)
      cursor = match.index + match[0].length
    }
    fragment.append(textNode.data.slice(cursor))
    textNode.replaceWith(fragment)
  }

  return parsedDocument.body.innerHTML
}
