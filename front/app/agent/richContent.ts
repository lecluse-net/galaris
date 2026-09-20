import { api } from '@/core/api'
import type { RichContentContribution } from '@/core/util'
import type { Agent } from './services/agentService'
export default {
  async search(query) {
    const { data } = await api.get<Agent[]>('/agents')
    return data.filter(agent => `${agent.first_name} ${agent.last_name} ${agent.job_title}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())).slice(0, 50).map(agent => ({ uri: `galaris://agent/${agent.id}`, title: `${agent.first_name} ${agent.last_name}`, context: agent.job_title ?? '' }))
  },
  href(uri) { const match = /^galaris:\/\/agent\/([1-9][0-9]*)$/.exec(uri); return match ? `/agent?agent_id=${match[1]}` : null },
} satisfies RichContentContribution
