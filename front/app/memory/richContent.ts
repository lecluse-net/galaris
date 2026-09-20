import { api } from '@/core/api'
import type { RichContentContribution } from '@/core/util'
import { memoryService } from './services/memoryService'
import type { MemorySearchPage } from './types'
export default {
  async search(query) {
    const { data: agents } = await api.get<{ id: number }[]>('/agents')
    const pages = await Promise.allSettled(agents.map(agent => memoryService.browse({ agentId: agent.id, query, limit: 50 })))
    const found = new Map<string, { uri: string; title: string; context: string }>()
    for (const result of pages) {
      if (result.status !== 'fulfilled') continue
      const page: MemorySearchPage = result.value
      for (const { item } of page.hits) found.set(item.id, { uri: `${item.node_kind === 'document' ? 'document' : 'memory'}://${item.id}`, title: item.title, context: `${item.memory_type} · ${item.owner_agent_id ?? item.owner_user_id ?? ''}` })
    }
    try {
      const library = await memoryService.browseDocumentLibrary({ query, limit: 50 })
      for (const entry of library.entries) found.set(entry.item.id, { uri: `document://${entry.item.id}`, title: entry.item.title, context: String(entry.item.owner_agent_id ?? entry.item.owner_user_id ?? '') })
    } catch { /* Library visibility is governed independently. */ }
    return [...found.values()]
  },
  href(uri) {
    const attachment = /^document:\/\/([0-9a-f-]{36})\/attachments\/([0-9a-f-]{36})$/.exec(uri)
    if (attachment) return `/memory/documents?document_id=${attachment[1]}&attachment_id=${attachment[2]}`

    const match = /^(document|memory):\/\/([0-9a-f-]{36})$/.exec(uri)
    if (match) return match[1] === 'document' ? `/memory/documents?document_id=${match[2]}` : `/memory?item_id=${match[2]}`
    return null
  },
} satisfies RichContentContribution
