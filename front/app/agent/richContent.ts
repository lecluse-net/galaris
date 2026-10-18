import { api } from '@/core/api'
import type { RichContentContribution } from '@/core/util'
import type { Agent } from './services/agentService'
import { agentResourceId } from './resourceUri'
import { agentService } from './services/agentService'
export default {
  async search(query) {
    const { data } = await api.get<Agent[]>('/agents')
    return data.filter(agent => `${agent.first_name} ${agent.last_name} ${agent.job_title}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())).slice(0, 50).map(agent => ({ uri: `galaris://agent/${agent.id}`, title: `${agent.first_name} ${agent.last_name}`, context: agent.job_title ?? '' }))
  },
  href(uri) { const match = /^galaris:\/\/agent\/([1-9][0-9]*)$/.exec(uri); return match ? `/agent?agent_id=${match[1]}` : null },
  target(uri, title = '', agentId = null) {
    const id = agentResourceId(uri)
    return id === null ? null : { kind: 'agent', id: String(id), title, agentId }
  },
  async card(uri) {
    const id = agentResourceId(uri)
    if (id === null) throw new Error('Invalid Agent reference')
    const { data: agent } = await agentService.getAgent(id)
    const card = document.createElement('blockquote')
    card.className = 'galaris-link-card galaris-agent-card'
    const title = document.createElement('p'), anchor = document.createElement('a'), name = document.createElement('strong')
    anchor.href = uri; name.textContent = `${agent.first_name} ${agent.last_name}`.trim()
    anchor.append(name); title.append(anchor); card.append(title)
    if (agent.job_title) { const role = document.createElement('p'); role.textContent = agent.job_title; card.append(role) }
    const address = document.createElement('p'); address.textContent = uri; card.append(address)
    return card.outerHTML
  },
} satisfies RichContentContribution
