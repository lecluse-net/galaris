import api from '@/core/api'
import type { AxiosResponse } from 'axios'
import { CONNECTIONS_CHANGED_EVENT } from '../events'

function connectionsChanged<T>(response: T): T {
    window.dispatchEvent(new Event(CONNECTIONS_CHANGED_EVENT))
    return response
}

// =============================================================================
// Parent Connection table contracts.
// =============================================================================

export interface Connection {
    id: number
    tool_id: number
    agent_id: number
    active: boolean
}

export interface ConnectionCreate {
    tool_id: number
    agent_id: number
    active?: boolean
}

export interface ConnectionUpdate {
    tool_id?: number
    agent_id?: number
    active?: boolean
}

// =============================================================================
// ConnectionParam EAV table contracts.
// =============================================================================

export interface ConnectionParam {
    id: number
    connection_id: number
    param_name: string
    param_value: string | null
}

export interface ConnectionParamCreate {
    connection_id: number
    param_name: string
    param_value: string | null
}

export interface ConnectionParamUpdate {
    param_value: string | null
}

export interface ConnectionParamsResponse {
    connection_id: number
    tool_id: number
    agent_id: number
    params: Record<string, unknown>
    configured_params: string[]
}

export interface ConnectionParamBulkCreate {
    connection_id: number
    params: Record<string, string | null>
}

export interface AgentByParamResponse {
    agent_ids: number[]
    count: number
}

export interface RefreshToolCatalogsResponse {
    created: number
    agents_scanned: number
    agents_refreshed: number
    agent_failures: number
    source_failures: number
    tools_discovered: number
    documents_indexed: number
    embeddings_refreshed: number
    documents_pruned: number
    semantic_available: boolean
    degradation_reason: string | null
    complete: boolean
}

// =============================================================================
// MCP test contracts.
// =============================================================================

export interface McpToolInfo {
    name: string
    description: string
}

export interface TestMcpToolsResponse {
    success: boolean
    message: string
    tools: McpToolInfo[]
}

// =============================================================================
// MCP function authorization contracts by connection.
// =============================================================================

// Tri-state function status at connection or tool level. "default" means no row,
// inheriting the active-by-default state; other values are explicit overrides.
export type FunctionState = 'default' | 'enabled' | 'disabled'

export interface ConnectionFunctionInfo {
    name: string
    description: string
    connection_state: FunctionState
    global_state: FunctionState
    effective: boolean
}

export interface ConnectionFunctionsResponse {
    success: boolean
    message: string
    functions: ConnectionFunctionInfo[]
}

export interface FunctionStateResolved {
    name: string
    connection_state: FunctionState
    global_state: FunctionState
    effective: boolean
}

// =============================================================================
// Service
// =============================================================================

export default {
    getConnections(
        tool_id?: number,
        agent_id?: number,
        active_only?: boolean,
        skip?: number,
        limit?: number
    ): Promise<AxiosResponse<Connection[]>> {
        const params: Record<string, unknown> = {}
        if (tool_id !== undefined) params.tool_id = tool_id
        if (agent_id !== undefined) params.agent_id = agent_id
        if (active_only !== undefined) params.active_only = active_only
        if (skip !== undefined) params.skip = skip
        params.limit = limit ?? 500
        return api.get('/connections', { params })
    },

    getConnection(id: number): Promise<AxiosResponse<Connection>> {
        return api.get(`/connections/${id}`)
    },

    createConnection(connection: ConnectionCreate): Promise<AxiosResponse<Connection>> {
        return api.post('/connections', connection).then(connectionsChanged)
    },

    updateConnection(id: number, connection: ConnectionUpdate): Promise<AxiosResponse<Connection>> {
        return api.patch(`/connections/${id}`, connection).then(connectionsChanged)
    },

    deleteConnection(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/connections/${id}`).then(connectionsChanged)
    },

    // Create missing internal connections, reload every live MCP catalog and rebuild its index.
    refreshToolCatalogs(): Promise<AxiosResponse<RefreshToolCatalogsResponse>> {
        return api.post('/connections/refresh-tools').then(connectionsChanged)
    },

    getConnectionParams(
        connectionId: number,
        decrypt: boolean = false
    ): Promise<AxiosResponse<ConnectionParamsResponse>> {
        return api.get(`/connections/${connectionId}/params`, { params: { decrypt } })
    },

    getSingleParam(connectionId: number, paramName: string): Promise<AxiosResponse<ConnectionParam>> {
        return api.get(`/connections/${connectionId}/params/${paramName}`)
    },

    createOrUpdateParam(param: ConnectionParamCreate): Promise<AxiosResponse<ConnectionParam>> {
        return api.post(`/connections/${param.connection_id}/params`, param)
    },

    createOrUpdateParamsBulk(
        connectionId: number,
        params: Record<string, string | null>
    ): Promise<AxiosResponse<ConnectionParam[]>> {
        const payload: ConnectionParamBulkCreate = { connection_id: connectionId, params }
        return api.post(`/connections/${connectionId}/params/bulk`, payload)
    },

    updateParam(
        connectionId: number,
        paramName: string,
        update: ConnectionParamUpdate
    ): Promise<AxiosResponse<ConnectionParam>> {
        return api.patch(`/connections/${connectionId}/params/${paramName}`, update)
    },

    deleteParam(connectionId: number, paramName: string): Promise<AxiosResponse<void>> {
        return api.delete(`/connections/${connectionId}/params/${paramName}`)
    },

    findAgentsByParam(
        toolId: number,
        paramName: string,
        paramValue: string
    ): Promise<AxiosResponse<AgentByParamResponse>> {
        return api.get('/connections/find-by-param', {
            params: { tool_id: toolId, param_name: paramName, param_value: paramValue }
        })
    },

    testMcpTools(
        tool_id: number,
        params: Record<string, string | null>
    ): Promise<AxiosResponse<TestMcpToolsResponse>> {
        return api.post<TestMcpToolsResponse>('/connections/test-mcp-tools', { tool_id, params })
    },

    getConnectionFunctions(connectionId: number): Promise<AxiosResponse<ConnectionFunctionsResponse>> {
        return api.get(`/connections/${connectionId}/functions`)
    },

    // Persist a function state directly at connection level.
    setConnectionFunctionState(
        connectionId: number,
        functionName: string,
        state: FunctionState
    ): Promise<AxiosResponse<FunctionStateResolved>> {
        return api.put(`/connections/${connectionId}/functions/${encodeURIComponent(functionName)}`, { state })
    },

    // Persist a function's global state at the connection's tool level.
    setToolFunctionState(
        connectionId: number,
        functionName: string,
        state: FunctionState
    ): Promise<AxiosResponse<FunctionStateResolved>> {
        return api.put(`/connections/${connectionId}/functions/${encodeURIComponent(functionName)}/global`, { state })
    }
}
