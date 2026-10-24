import type { RichContentContribution } from '@/core/util'
import { referenceId, referenceCardHtml, referenceDate } from '@/core/util/facade'
import { topicService } from './services/topicService'
const idFrom = (uri: string) => referenceId(uri, 'topic', '/topic')
export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://topic/${id}` : null },
  async search(query) {
    return (await topicService.list({ search: query, limit: 50 })).items.map(topic => ({ uri: `galaris://topic/${topic.id}`, title: topic.title, context: topic.keywords.join(' · ') }))
  },
  href(uri) { const id = idFrom(uri); return id ? `/topic/${id}` : null },
  target(uri, title = '') { const id = idFrom(uri); return id ? { kind: 'topic', id, title } : null },
  async title(uri) { const id = idFrom(uri); return id ? (await topicService.get(id)).title : uri },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Topic reference')
    const topic = await topicService.get(id)
    return referenceCardHtml(`galaris://topic/${id}`, topic.title, [referenceDate(topic.updated_at || topic.created_at, formatting), ...topic.keywords], [topic.description])
  },
} satisfies RichContentContribution
