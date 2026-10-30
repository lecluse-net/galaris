import { api } from '@/core/api'
import { type RichContentContribution } from '@/core/util'
import { memoryService } from './services/memoryService'
import type { MemorySearchPage } from './types'
import { contactResourceId } from './contactResource'
import { referenceId } from '@/core/util/facade'
export default {
  canonical(value) {
    const id = referenceId(value, 'contact', '/memory/contacts', 'contact_id')
    return id ? `galaris://contact/${id}` : null
  },
  async search(query) {
    const { data: agents } = await api.get<{ id: number }[]>('/agents')
    const pages = await Promise.allSettled(agents.map(agent => memoryService.browse({ agentId: agent.id, query, nodeKinds: ['memory'], limit: 50 })))
    const found = new Map<string, { uri: string; title: string; context: string }>()
    for (const result of pages) {
      if (result.status !== 'fulfilled') continue
      const page: MemorySearchPage = result.value
      for (const { item } of page.hits) {
        if (item.node_kind !== 'memory') continue
        found.set(item.id, { uri: `memory://${item.id}`, title: item.title, context: `${item.owner_agent_id ?? item.owner_user_id ?? ''}` })
      }
    }
    return [...found.values()]
  },
  href(uri) {
    const contact = contactResourceId(uri)
    if (contact) return `/memory/contacts?contact_id=${contact}`
    const match = /^memory:\/\/([0-9a-f-]{36})$/.exec(uri)
    return match ? `/memory?item_id=${match[1]}` : null
  },
  target(uri, title = '', agentId = null) {
    const contact = contactResourceId(uri)
    if (contact) return { kind: 'contact', id: contact, title, agentId }
    const match = /^memory:\/\/([0-9a-f-]{36})$/.exec(uri)
    return match ? { kind: 'memory', id: match[1]!, title, agentId } : null
  },
  canCard: uri => contactResourceId(uri) !== null,
  async title(uri) {
    const id = contactResourceId(uri)
    return id ? (await (await import('./services/contactService')).contactService.get(id)).display_name : uri
  },
  async card(uri) {
    const id = contactResourceId(uri)
    if (!id) throw new Error('Invalid Contact reference')
    const contact = await (await import('./services/contactService')).contactService.get(id)
    const card = document.createElement('blockquote'), paragraph = document.createElement('p')
    const link = document.createElement('a'), title = document.createElement('strong')
    card.className = 'galaris-link-card galaris-contact-card'
    link.href = uri; title.textContent = contact.display_name; link.append(title); paragraph.append(link); card.append(paragraph)
    const address = document.createElement('p'); address.textContent = uri; card.append(address)
    return card.outerHTML
  },
} satisfies RichContentContribution
