import type { RichContentContribution } from '@/core/util'
import { goalService } from './services/goalService'
import { referenceId, referenceCardHtml, referenceDate, referenceStatus } from '@/core/util'
const idFrom = (uri: string) => referenceId(uri, 'goal', '/goal', 'goal_id')
export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://goal/${id}` : null },
  async search(query, formatting) {
    const page = await goalService.list({ search: query, limit: 50 })
    return page.items.map(goal => ({ uri: `galaris://goal/${goal.id}`, title: goal.title, context: [formatting.t('nav.goal'), goal.agent_name].join(' · ') }))
  },
  href(uri) { const id = idFrom(uri); return id ? `/goal?goal_id=${id}` : null },
  target(uri, title = '', agentId = null) {
    const id = idFrom(uri)
    return id ? { kind: 'goal', id, title, agentId } : null
  },
  async title(uri) { const id = idFrom(uri); return id ? (await goalService.get(id)).title : uri },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Goal reference')
    const goal = await goalService.get(id)
    return referenceCardHtml(`galaris://goal/${id}`, goal.title, [goal.agent_name, referenceDate(goal.created_at, formatting), referenceStatus('goal.statuses', goal.status, formatting)])
  },
} satisfies RichContentContribution
