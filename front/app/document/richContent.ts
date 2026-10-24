import type { RichContentContribution } from '@/core/util'
import { documentIdFromResourceUri } from '@/core/util/facade'
import { documentService } from './services/documentService'
export default {
  previewImage: (uri, agentId, signal) => documentService.linkThumbnail(uri, agentId, signal),
  async search(query) {
    const library = await documentService.browseDocumentLibrary({ query, limit: 50, include_keywords: false })
    return library.entries.map(({ item }) => ({ uri: `document://${item.id}`, title: item.title, context: String(item.owner_agent_id ?? item.owner_user_id ?? '') }))
  },
  href(uri) {
    const attachment = /^document:\/\/([0-9a-f-]{36})\/attachments\/([0-9a-f-]{36})$/.exec(uri)
    if (attachment) return `/documents?document_id=${attachment[1]}&attachment_id=${attachment[2]}`

    const match = /^(document):\/\/([0-9a-f-]{36})$/.exec(uri)
    if (match) return `/documents?document_id=${match[2]}`
    return null
  },
  target(uri, title = '', agentId = null) {
    const match = /^(document):\/\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)
    return match ? { kind: match[1]!, id: match[2]!, title, agentId } : null
  },
  async title(uri) {
    const id = documentIdFromResourceUri(uri)
    return id ? (await documentService.getManagedDocument(id)).item.title : uri
  },
  canCard: uri => documentIdFromResourceUri(uri) !== null,
  async card(uri) {
    const id = documentIdFromResourceUri(uri)
    if (!id) throw new Error('Invalid Document reference')
    const { item } = await documentService.getManagedDocument(id)
    const card = document.createElement('blockquote'), paragraph = document.createElement('p')
    const anchor = document.createElement('a'), title = document.createElement('strong')
    card.className = 'galaris-link-card'
    anchor.href = `document://${id}`; title.textContent = item.title
    anchor.append(title); paragraph.append(anchor); card.append(paragraph)
    const identifier = document.createElement('p'); identifier.textContent = id; card.append(identifier)
    return card.outerHTML
  },
} satisfies RichContentContribution
