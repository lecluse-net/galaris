import api from '@/core/api'

export interface HomeConversationMessage {
  text: string
  created_at: string
}

export interface HomeConversation {
  id: string
  label: string
  agent_name: string
  source: string | null
  messenger_label: string
  messenger_active: boolean
  unread_count: number
  last_message: HomeConversationMessage | null
}

interface HomeConversationPage {
  items: HomeConversation[]
  total: number
  page: number
  page_size: number
}

export interface HomeRecentTask {
  id: string
  label: string
  status: string
  created_at: string
}

interface HomeTaskPage {
  items: HomeRecentTask[]
}

export interface HomeRecentProcess {
  id: string
  process_label: string | null
  workflow_id: string | null
  status: string
  created_at: string
}

interface HomeProcessPage {
  items: HomeRecentProcess[]
}

export interface HomeRecentMemory {
  id: string
  title: string
  memory_type: string
  created_at: string
}

export interface HomeRecentIncident {
  id: string
  kind: string
  recovered_at: string | null
  occurred_at: string
}

interface HomeIncidentPage {
  items: HomeRecentIncident[]
  total: number
}

async function getRecentConversations(): Promise<HomeConversation[]> {
  const response = await api.get<HomeConversationPage>('/chat/rooms', {
    params: {
      page: 1,
      page_size: 50,
      include_external: true,
    },
  })
  return response.data.items.filter(room => room.messenger_active)
}

async function getRecentTasks(): Promise<HomeRecentTask[]> {
  const response = await api.get<HomeTaskPage>('/tasks/recent', {
    params: { skip: 0, limit: 8 },
  })
  return response.data.items
}

async function getRecentProcesses(): Promise<HomeRecentProcess[]> {
  const response = await api.get<HomeProcessPage>('/processes/runs', {
    params: {
      page: 1,
      page_size: 8,
      sort_by: 'created_at',
      descending: true,
    },
  })
  return response.data.items
}

async function getRecentMemories(): Promise<HomeRecentMemory[]> {
  const response = await api.get<HomeRecentMemory[]>('/memory/recent', {
    params: { limit: 8 },
  })
  return response.data
}

async function getRecentIncidents(): Promise<HomeIncidentPage> {
  const response = await api.get<HomeIncidentPage>('/incidents/recent', {
    params: { page_size: 5 },
  })
  return response.data
}

export const homeService = {
  getRecentConversations,
  getRecentTasks,
  getRecentProcesses,
  getRecentMemories,
  getRecentIncidents,
}
