import api from '@/core/api'
import type { AxiosResponse } from 'axios'

// Access token for an agent's unified MCP server (see back/app/mcp).
export interface AgentMcpToken {
    id: number
    agent_id: number
    label: string | null
    token: string // Masked after the clear-text value is returned once at creation.
    enabled: boolean
    created_at: string
}

export interface AgentMcpTokenCreate {
    label?: string
    enabled?: boolean
}

export interface AgentMcpTokenUpdate {
    label?: string
    enabled?: boolean
}

export const mcpTokenService = {
    listTokens(agentId: number): Promise<AxiosResponse<AgentMcpToken[]>> {
        return api.get(`/agents/${agentId}/mcp-tokens`)
    },
    createToken(agentId: number, data: AgentMcpTokenCreate = {}): Promise<AxiosResponse<AgentMcpToken>> {
        return api.post(`/agents/${agentId}/mcp-tokens`, data)
    },
    updateToken(agentId: number, tokenId: number, data: AgentMcpTokenUpdate): Promise<AxiosResponse<AgentMcpToken>> {
        return api.put(`/agents/${agentId}/mcp-tokens/${tokenId}`, data)
    },
    deleteToken(agentId: number, tokenId: number): Promise<AxiosResponse<void>> {
        return api.delete(`/agents/${agentId}/mcp-tokens/${tokenId}`)
    },
}
