import { api } from '@/core/api'
import type { RichContentContribution } from '@/core/util'
import type { Task } from './types'
import { referenceId, referenceCardHtml, referenceDate, referenceStatus } from '@/core/util'
import { taskService } from './services/taskService'
import { pauseBadge } from './services/taskStatusService'
const idFrom = (uri: string) => referenceId(uri, 'task', '/task', 'task_id')
export default {
  schemes: ['galaris'],
  canonical(value) { const id = idFrom(value); return id ? `galaris://task/${id}` : null },
  async search(query, formatting) {
    const { data } = await api.get<{ items: Task[] }>('/tasks/recent', { params: { limit: 50, q: query } })
    return data.items.filter(task => task.label.toLocaleLowerCase().includes(query.toLocaleLowerCase())).map(task => ({ uri: `galaris://task/${task.id}`, title: task.label, context: [formatting.t('task.tabs.tasks'), referenceDate(task.created_at, formatting), referenceStatus('task.status', task.status, formatting)].filter(Boolean).join(' · ') }))
  },
  href(uri) { const id = idFrom(uri); return id ? `/task?task_id=${id}` : null },
  target(uri, title = '', agentId = null) {
    const id = idFrom(uri)
    return id ? { kind: 'task', id, title, agentId } : null
  },
  async title(uri) { const id = idFrom(uri); return id ? (await taskService.getById(id)).label : uri },
  async card(uri, _agentId, formatting) {
    const id = idFrom(uri)
    if (!id) throw new Error('Invalid Task reference')
    const { task, agent } = await taskService.getByIdWithAgent(id)
    const pause = pauseBadge(task)
    return referenceCardHtml(`galaris://task/${id}`, task.label, [
      agent ? `${agent.first_name} ${agent.last_name}`.trim() : task.agent_id ? formatting.t('task.list.agentId', { id: task.agent_id }) : formatting.t('task.list.noAgent'),
      referenceDate(task.created_at, formatting), referenceStatus('task.status', task.status, formatting), pause && formatting.t(pause.labelKey),
    ])
  },
} satisfies RichContentContribution
