import type { RichContentContribution } from '@/core/util'
import { referenceId, referenceCardHtml, referenceDate, referenceStatus } from '@/core/util/facade'
import { conversationService } from './services/conversationService'
const idFrom = (uri: string) => referenceId(uri, 'text', '/task', 'round_id')
export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://text/${id}` : null },
  async search(query, formatting) {
    const page = await conversationService.listMessages({ search: query, pageSize: 50 })
    return [...new Map(page.items.filter(item => item.round_id).map(item => [item.round_id, {
      uri: `galaris://text/${item.round_id}`, title: formatting.t('conversation.history.detail.turn'), context: [item.agent_name, item.channel_kind, referenceDate(item.created_at, formatting)].filter(Boolean).join(' · '),
    }])).values()]
  },
  href(uri) { const id = idFrom(uri); return id ? `/task?round_id=${id}` : null },
  target(uri, title = '') { const id = idFrom(uri); return id ? { kind: 'round', id, title } : null },
  async title(uri, _agentId, formatting) { const id = idFrom(uri); if (!id) return uri; const round = await conversationService.getRound(id); return [formatting.t('conversation.history.detail.turn'), round.agent_name, referenceDate(round.created_at, formatting)].filter(Boolean).join(' · ') },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Round reference')
    const round = await conversationService.getRound(id)
    return referenceCardHtml(`galaris://text/${id}`, formatting.t('conversation.history.detail.turn'), [round.agent_name, referenceDate(round.created_at, formatting), round.channel_kind,
      referenceStatus('conversation.history.detail.roundStatuses', round.status, formatting), round.room_id])
  },
} satisfies RichContentContribution
