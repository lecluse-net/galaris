import type { RichContentContribution } from '@/core/util'
import { goalService } from './services/goalService'
export default {
  async search(query) {
    const page = await goalService.list({ search: query, limit: 50 })
    return page.items.map(goal => ({ uri: `galaris://goal/${goal.id}`, title: goal.title, context: `Goal · ${goal.agent_id}` }))
  },
  href(uri) { const match = /^galaris:\/\/goal\/([0-9a-f-]{36})$/.exec(uri); return match ? `/goal?goal_id=${match[1]}` : null },
} satisfies RichContentContribution
