import { api } from '@/core/api'
import type { RichContentContribution } from '@/core/util'
import type { Task } from './types'
export default {
  async search(query) {
    const { data } = await api.get<{ items: Task[] }>('/tasks/recent', { params: { limit: 50, q: query } })
    return data.items.filter(task => task.label.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(task => ({ uri: `galaris://task/${task.id}`, title: task.label, context: `Task · ${task.agent_id}` }))
  },
  href(uri) { const match = /^galaris:\/\/task\/([0-9a-f-]{36})$/.exec(uri); return match ? `/task?task_id=${match[1]}` : null },
  target(uri, title = '', agentId = null) {
    const match = /^galaris:\/\/task\/([0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$/.exec(uri)
    return match ? { kind: 'task', id: match[1]!, title, agentId } : null
  },
} satisfies RichContentContribution
