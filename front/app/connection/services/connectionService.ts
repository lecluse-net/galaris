import api, { sessionGeneration, SupersededSessionError } from '@/core/api'
import type { AxiosRequestConfig, AxiosResponse } from 'axios'
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

// "default" means no saved rule: a connection uses the global policy, and a tool
// uses the software policy returned as default_state. Other values are explicit rules.
export type FunctionState = 'default' | 'enabled' | 'disabled' | 'ask'
export type EffectiveFunctionState = Exclude<FunctionState, 'default'>

export interface ConnectionFunctionInfo {
    key: string
    name: string
    description: string
    connection_state: FunctionState
    global_state: FunctionState
    effective: boolean
    capability_kind: 'tool' | 'resource' | 'prompt'
    effective_state: EffectiveFunctionState
    default_state: EffectiveFunctionState
    state_source: 'connection' | 'tool' | 'native_default' | 'external_default'
}

export interface ConnectionFunctionsResponse {
    success: boolean
    message: string
    functions: ConnectionFunctionInfo[]
}

export interface FunctionStateResolved {
    local_override_count?: number
    name: string
    connection_state: FunctionState
    global_state: FunctionState
    effective: boolean
    effective_state: EffectiveFunctionState
    default_state: EffectiveFunctionState
    state_source: ConnectionFunctionInfo['state_source']
}

export interface FunctionPolicyChange {
    scope: 'connection' | 'global'
    state: EffectiveFunctionState
}

// Global and local choices for one capability share an ordered write stream,
// including when its connection changes or the manager is reopened.
const functionPolicyWrites = new Map<string, Promise<AxiosResponse<FunctionStateResolved>>>()

export async function waitForFunctionPolicyWrites(toolId: number): Promise<void> {
    await Promise.allSettled([...functionPolicyWrites.entries()]
        .filter(([key]) => key.startsWith(`${toolId}:`))
        .map(([, pending]) => pending))
}

export function saveFunctionPolicy(
    connection: Connection,
    capability: Pick<ConnectionFunctionInfo, 'name' | 'capability_kind'>,
    change: FunctionPolicyChange,
): Promise<AxiosResponse<FunctionStateResolved>> {
    const key = `${connection.tool_id}:${JSON.stringify([capability.capability_kind, capability.name])}`
    const generation = sessionGeneration()
    const config: AxiosRequestConfig & { _sessionGeneration: string } = { _sessionGeneration: generation }
    const previous = functionPolicyWrites.get(key)
    const write = (previous ? previous.catch(() => undefined) : Promise.resolve()).then(() => {
        if (generation !== sessionGeneration()) throw new SupersededSessionError()
        return api.put<FunctionStateResolved>(`/connections/${connection.id}/capabilities`, {
            function_name: capability.name,
            capability_kind: capability.capability_kind,
            state: change.state,
            ...(change.scope === 'global' ? { global_policy: true, inherit_connection: true } : {}),
        }, config)
    })
    functionPolicyWrites.set(key, write)
    const cleanup = () => {
        if (functionPolicyWrites.get(key) === write) functionPolicyWrites.delete(key)
    }
    void write.then(cleanup, cleanup)
    return write
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
        state: FunctionState,
        capabilityKind: 'tool' | 'resource' | 'prompt' = 'tool'
    ): Promise<AxiosResponse<FunctionStateResolved>> {
        return api.put(`/connections/${connectionId}/capabilities`, { state, function_name: functionName, capability_kind: capabilityKind })
    },

    // Persist the global state, optionally returning this connection to inheritance.
    setToolFunctionState(
        connectionId: number,
        functionName: string,
        state: FunctionState,
        capabilityKind: 'tool' | 'resource' | 'prompt' = 'tool',
        inheritConnection: boolean = false
    ): Promise<AxiosResponse<FunctionStateResolved>> {
        return api.put(`/connections/${connectionId}/capabilities`, {
            state, function_name: functionName, capability_kind: capabilityKind, global_policy: true,
            inherit_connection: inheritConnection,
        })
    }
}
