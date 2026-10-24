import api from '@/core/api'

export interface MissionAgent { agent_id: number; display_name: string; active: boolean }
export interface MissionJob { room: string; client: string; text: string; message: string | null }
export interface MissionTask { id: string; label: string; status: string; paused: boolean }
export interface MissionDocument { id: string; label: string; uri: string }

export const firstMissionService = {
  async agents(signal: AbortSignal): Promise<MissionAgent[]> {
    const status = (await api.get<{ enabled: boolean; chat_enabled: boolean }>('/chat/status', { signal })).data
    if (!status.enabled || !status.chat_enabled) return []
    return (await api.get<{ agents: MissionAgent[] }>('/chat/recipients', { params: { page: 1, page_size: 500 }, signal })).data.agents.filter(agent => agent.active)
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
