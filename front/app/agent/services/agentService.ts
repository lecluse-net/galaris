import api from '@/core/api'
import type { AxiosResponse } from 'axios'

// Title interfaces
export interface Title {
    id: number
    label: string
    gender: 'M' | 'F'
}

export interface TitleCreate {
    label: string
    gender: 'M' | 'F'
}

export interface TitleUpdate extends Partial<TitleCreate> { }

// Executor driver used by the agent_driver selector. Source: GET /agents/drivers.
export interface ExecutorDriverInfo {
    name: string
    label_key: string
    available: boolean
    manages_runtime: boolean
}

// Agent group interfaces
export interface AgentGroup {
    id: number
    name: string
    order: number
}

export interface AgentGroupCreate {
    name: string
    order?: number
}

export interface AgentGroupUpdate extends Partial<AgentGroupCreate> { }

export interface AgentModelInfo {
    id: number
    code: string
    label: string
    llm_name: string
}

// Model profile summary exposed by GET /agents (see LlmProfileInfo in the API).
export interface LlmProfileInfo {
    id: number
    label: string
}

export interface AgentManagerInfo {
    id: number
    email: string
    display_name: string | null
    is_current_user: boolean
}

// Agent interfaces
export interface Agent {
    id: number
    user_id: number
    user: AgentManagerInfo
    is_owner: boolean
    memory_item_id: string | null
    title_id: number
    group_id: number | null
    team_ids: number[]
    code: string
    first_name: string
    last_name: string
    personality: string | null
    job_description: string | null
    job_title: string | null
    agent_driver: string
    task_harness_id: string | null
    profile_id: number | null
    voice: string | null
    profile?: LlmProfileInfo | null
    has_avatar: boolean
    title?: Title
}

export interface AgentCreate {
    user_id?: number | null
    title_id: number
    group_id?: number | null
    code: string
    first_name: string
    last_name?: string
    personality?: string | null
    job_description?: string | null
    job_title?: string | null
    agent_driver?: string
    profile_id?: number | null
    voice?: string | null
}

export type AgentUpdate = Partial<Omit<AgentCreate, 'code'>>

// Title service
export const titleService = {
    getTitles(): Promise<AxiosResponse<Title[]>> {
        return api.get('/agents/titles', { params: { limit: 500 } })
    },
    getTitle(id: number): Promise<AxiosResponse<Title>> {
        return api.get(`/agents/titles/${id}`)
    },
    createTitle(title: TitleCreate): Promise<AxiosResponse<Title>> {
        return api.post('/agents/titles', title)
    },
    updateTitle(id: number, title: TitleUpdate): Promise<AxiosResponse<Title>> {
        return api.put(`/agents/titles/${id}`, title)
    },
    deleteTitle(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/agents/titles/${id}`)
    }
}

// Agent group service
export const agentGroupService = {
    getGroups(): Promise<AxiosResponse<AgentGroup[]>> {
        return api.get('/agents/groups', { params: { limit: 500 } })
    },
    getGroup(id: number): Promise<AxiosResponse<AgentGroup>> {
        return api.get(`/agents/groups/${id}`)
    },
    createGroup(group: AgentGroupCreate): Promise<AxiosResponse<AgentGroup>> {
        return api.post('/agents/groups', group)
    },
    updateGroup(id: number, group: AgentGroupUpdate): Promise<AxiosResponse<AgentGroup>> {
        return api.put(`/agents/groups/${id}`, group)
    },
    deleteGroup(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/agents/groups/${id}`)
    }
}

// Agent service
export const agentService = {
    async getAgents(): Promise<AxiosResponse<Agent[]>> {
        // Consumers build complete trees and local selectors; traverse every page.
        const response = await api.get<Agent[]>('/agents', { params: { skip: 0, limit: 500 } })
        const agents = [...response.data]
        let size = response.data.length
        while (size === 500) {
            const next = await api.get<Agent[]>('/agents', { params: { skip: agents.length, limit: 500 } })
            agents.push(...next.data)
            size = next.data.length
        }
        return { ...response, data: agents }
    },
    getAgent(id: number): Promise<AxiosResponse<Agent>> {
        return api.get(`/agents/${id}`)
    },
    getManagers(): Promise<AxiosResponse<AgentManagerInfo[]>> {
        return api.get('/agents/managers')
    },
    createAgent(agent: AgentCreate): Promise<AxiosResponse<Agent>> {
        return api.post('/agents', agent, { headers: { 'X-Editorial-Profile-Version': '1' } })
    },
    updateAgent(id: number, agent: AgentUpdate): Promise<AxiosResponse<Agent>> {
        return api.put(`/agents/${id}`, agent, { headers: { 'X-Editorial-Profile-Version': '1' } })
    },
    deleteAgent(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/agents/${id}`)
    },
    uploadAvatar(id: number, file: File): Promise<AxiosResponse<void>> {
        const formData = new FormData()
        formData.append('file', file)
        return api.post(`/agents/${id}/avatar`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data'
            }
        })
    },
    getAvatarUrl(id: number): string {
        return `/api/agents/${id}/avatar`
    },
    async getAvatarBlobUrl(id: number): Promise<string> {
        const response = await api.get(`/agents/${id}/avatar`, {
            responseType: 'blob'
        })
        return URL.createObjectURL(response.data)
    },
    deleteAvatar(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/agents/${id}/avatar`)
    },
    getDrivers(): Promise<AxiosResponse<ExecutorDriverInfo[]>> {
        return api.get('/agents/drivers')
    }
}

export default {
    titleService,
    agentGroupService,
    agentService
}
