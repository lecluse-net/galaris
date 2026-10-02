import api, { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { createSessionReadCache, createSessionResponseCache, invalidateSessionReads, queuePreview } from '@/core/util/facade'
import type { AxiosResponse } from 'axios'

const avatars = createSessionReadCache<Blob>({
    sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration,
    group: 'agent-avatar', maxAgeMs: 60_000, maxEntries: 64, maxBytes: 16 * 1024 * 1024, size: blob => blob.size,
})

const referenceOptions = { sessionEvent: AUTH_TOKEN_CHANGED_EVENT, sessionKey: sessionGeneration, maxAgeMs: 60_000 }
const agents = createSessionResponseCache<Agent[]>({ ...referenceOptions, group: 'agent-catalogue' })
const titles = createSessionResponseCache<Title[]>({ ...referenceOptions, group: 'agent-titles', maxAgeMs: 300_000 })
const groups = createSessionResponseCache<AgentGroup[]>({ ...referenceOptions, group: 'agent-groups', maxAgeMs: 300_000 })

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
    yolo: boolean
    authorization_version: number
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
    avatar_revision?: number
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
    getTitles(force = false): Promise<AxiosResponse<Title[]>> {
        return titles.read(async signal => {
            const response = await api.get<Title[]>('/agents/titles', { params: { skip: 0, limit: 500 }, signal })
            const catalogue = [...response.data]
            let size = response.data.length
            while (size === 500) {
                const next = await api.get<Title[]>('/agents/titles', { params: { skip: catalogue.length, limit: 500 }, signal })
                catalogue.push(...next.data)
                size = next.data.length
            }
            return { ...response, data: catalogue }
        }, force)
    },
    getTitle(id: number): Promise<AxiosResponse<Title>> {
        return api.get(`/agents/titles/${id}`)
    },
    async createTitle(title: TitleCreate): Promise<AxiosResponse<Title>> {
        const response = await api.post<Title>('/agents/titles', title)
        invalidateSessionReads('agent-titles')
        return response
    },
    async updateTitle(id: number, title: TitleUpdate): Promise<AxiosResponse<Title>> {
        const response = await api.put<Title>(`/agents/titles/${id}`, title)
        invalidateSessionReads('agent-titles')
        invalidateSessionReads('agent-catalogue')
        invalidateSessionReads('agent-selection')
        return response
    },
    async deleteTitle(id: number): Promise<AxiosResponse<void>> {
        const response = await api.delete(`/agents/titles/${id}`)
        invalidateSessionReads('agent-titles')
        invalidateSessionReads('agent-catalogue')
        invalidateSessionReads('agent-selection')
        return response
    }
}

// Agent group service
export const agentGroupService = {
    getGroups(force = false): Promise<AxiosResponse<AgentGroup[]>> {
        return groups.read(signal => api.get('/agents/groups', { params: { limit: 500 }, signal }), force)
    },
    getGroup(id: number): Promise<AxiosResponse<AgentGroup>> {
        return api.get(`/agents/groups/${id}`)
    },
    async createGroup(group: AgentGroupCreate): Promise<AxiosResponse<AgentGroup>> {
        const response = await api.post<AgentGroup>('/agents/groups', group)
        invalidateSessionReads('agent-groups')
        return response
    },
    async updateGroup(id: number, group: AgentGroupUpdate): Promise<AxiosResponse<AgentGroup>> {
        const response = await api.put<AgentGroup>(`/agents/groups/${id}`, group)
        invalidateSessionReads('agent-groups')
        return response
    },
    async deleteGroup(id: number): Promise<AxiosResponse<void>> {
        const response = await api.delete(`/agents/groups/${id}`)
        invalidateSessionReads('agent-groups')
        invalidateSessionReads('agent-catalogue')
        return response
    }
}

// Agent service
export const agentService = {
    async setYolo(id: number, enabled: boolean, expectedVersion: number, acknowledged = false) {
        const response = await api.put<{ yolo: boolean; authorization_version: number }>(`/agents/${id}/yolo`, { enabled, acknowledged, expected_version: expectedVersion })
        invalidateSessionReads('agent-catalogue')
        return response.data
    },
    getAgents(force = false): Promise<AxiosResponse<Agent[]>> {
      return agents.read(async signal => {
        // Consumers build complete trees and local selectors; traverse every page.
        const response = await api.get<Agent[]>('/agents', { params: { skip: 0, limit: 500 }, signal })
        const agents = [...response.data]
        let size = response.data.length
        while (size === 500) {
            const next = await api.get<Agent[]>('/agents', { params: { skip: agents.length, limit: 500 }, signal })
            agents.push(...next.data)
            size = next.data.length
        }
        return { ...response, data: agents }
      }, force)
    },
    getAgent(id: number): Promise<AxiosResponse<Agent>> {
        return api.get(`/agents/${id}`)
    },
    getManagers(): Promise<AxiosResponse<AgentManagerInfo[]>> {
        return api.get('/agents/managers')
    },
    async createAgent(agent: AgentCreate): Promise<AxiosResponse<Agent>> {
        const response = await api.post('/agents', agent, { headers: { 'X-Editorial-Profile-Version': '1' } })
        invalidateSessionReads('agent-selection')
        invalidateSessionReads('agent-catalogue')
        return response
    },
    async updateAgent(id: number, agent: AgentUpdate): Promise<AxiosResponse<Agent>> {
        const response = await api.put(`/agents/${id}`, agent, { headers: { 'X-Editorial-Profile-Version': '1' } })
        invalidateSessionReads('agent-avatar')
        invalidateSessionReads('agent-selection')
        invalidateSessionReads('agent-catalogue')
        return response
    },
    async deleteAgent(id: number): Promise<AxiosResponse<void>> {
        const response = await api.delete(`/agents/${id}`)
        invalidateSessionReads('agent-avatar')
        invalidateSessionReads('agent-selection')
        invalidateSessionReads('agent-catalogue')
        return response
    },
    async uploadAvatar(id: number, file: File): Promise<AxiosResponse<void>> {
        const formData = new FormData()
        formData.append('file', file)
        const response = await api.post(`/agents/${id}/avatar`, formData, {
            headers: {
                'Content-Type': 'multipart/form-data'
            }
        })
        invalidateSessionReads('agent-avatar')
        invalidateSessionReads('agent-selection')
        invalidateSessionReads('agent-catalogue')
        return response
    },
    getAvatarUrl(id: number): string {
        return `/api/agents/${id}/avatar`
    },
    async getAvatarBlobUrl(id: number, signal?: AbortSignal, revision = 0): Promise<string> {
        const blob = await avatars.read(`${id}:${revision}`, sharedSignal => queuePreview(async () => (
            await api.get<Blob>(`/agents/${id}/avatar`, { responseType: 'blob', signal: sharedSignal, params: { revision } })
        ).data, sharedSignal), signal)
        signal?.throwIfAborted()
        return URL.createObjectURL(blob)
    },
    async deleteAvatar(id: number): Promise<AxiosResponse<void>> {
        const response = await api.delete(`/agents/${id}/avatar`)
        invalidateSessionReads('agent-avatar')
        invalidateSessionReads('agent-selection')
        invalidateSessionReads('agent-catalogue')
        return response
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
