import api from '@/core/api'

export interface MissionAgent { agent_id: number; display_name: string; active: boolean; team_heading?: string; without_team?: boolean }
interface AgentTeams { id: number; teams?: { id: number; name: string; order: number }[] }
export interface MissionJob { room: string; client: string; text: string; message: string | null }
export interface MissionTask { id: string; label: string; status: string; paused: boolean }
export interface MissionDocument { id: string; label: string; uri: string }

export const firstMissionService = {
  async agents(signal: AbortSignal): Promise<MissionAgent[]> {
    const status = (await api.get<{ enabled: boolean; chat_enabled: boolean }>('/chat/status', { signal })).data
    if (!status.enabled || !status.chat_enabled) return []
    const agents = (await api.get<{ agents: MissionAgent[] }>('/chat/recipients', { params: { page: 1, page_size: 500 }, signal })).data.agents.filter(agent => agent.active)
    let memberships: AgentTeams[]
    try { memberships = (await api.get<AgentTeams[]>('/agents/selection', { params: { scope: 'dialogue' }, signal })).data }
    catch (error) { if (signal.aborted) throw error; return agents }
    const byId = new Map(memberships.map(agent => [agent.id, agent.teams ?? []]))
    const teams = [...new Map(memberships.flatMap(agent => (agent.teams ?? []).map(team => [team.id, team] as const))).values()]
      .sort((a, b) => a.order - b.order || a.id - b.id)
    const unassigned = agents.filter(agent => !byId.get(agent.agent_id)?.length)
    return [
      ...teams.flatMap(team => agents.filter(agent => byId.get(agent.agent_id)?.some(value => value.id === team.id))
        .map((agent, index) => ({ ...agent, team_heading: index === 0 ? team.name : undefined }))),
      ...unassigned.map((agent, index) => ({ ...agent, without_team: index === 0 })),
    ]
  },
  async createRoom(agent: number, label: string): Promise<string> {
    return (await api.post<{ id: string }>('/chat/rooms', { agent_id: agent, label, topic_id: null, show_last_message: true })).data.id
  },
  async send(job: MissionJob, language: string): Promise<string> {
    return (await api.post<{ id: string }>(`/chat/rooms/${job.room}/messages`, {
      client_message_id: job.client, text: job.text, language, task_requested: true,
    })).data.id
  },
  async progress(job: MissionJob, signal: AbortSignal): Promise<{ tasks: MissionTask[]; documents: MissionDocument[] }> {
    const tasks = (await api.get<{ items: MissionTask[] }>(`/chat/rooms/${job.room}/tasks`, {
      params: { page: 1, page_size: 50 }, signal,
    })).data.items
    const documents = job.message ? (await api.get<{ items: MissionDocument[] }>(`/chat/rooms/${job.room}/documents`, {
      params: { from_message_id: job.message, page: 1, page_size: 50 }, signal,
    })).data.items : []
    return { tasks, documents }
  },
}
