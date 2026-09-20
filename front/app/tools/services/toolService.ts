import api from '@/core/api'
import type { AxiosResponse } from 'axios'

// =============================================================================
// Types
// =============================================================================

export interface McpAuth {
    type: 'bearer' | 'header' | 'basic' | 'none'
    header_name?: string
    param?: string
    login_param?: string
    password_param?: string
    // Write-only legacy field. Read responses expose presence only.
    token_static?: string
    token_static_configured?: boolean
    url_param?: string
}

export interface McpConfig {
    type: 'sse' | 'http' | 'stdio'
    url?: string
    command?: string
    args?: string[]
    env?: Record<string, string>
    headers?: Record<string, string>
    auth?: McpAuth
    timeout?: number
}

export interface FileShareConfig {
    service: string
    base_url: string
    // Bridge parameter key -> connection parameter name.
    param_map: Record<string, string>
}

// File-share bridge metadata returned by GET /file-share/bridges and used to
// generate the configuration form dynamically.
export interface FileShareBridgeParam {
    key: string
    label: string
    type: string
    required: boolean
}

export interface FileShareBridge {
    service: string
    label: string
    supports_share: boolean
    params: FileShareBridgeParam[]
}

export interface MessengerConfig {
    service: string
    // Server-level bridge values shared by every connection to this Tool.
    settings: Record<string, string>
    // Bridge parameter key -> connection parameter name.
    param_map: Record<string, string>
}

export interface MessengerBridgeParam {
    key: string
    label: string
    type: string
    required: boolean
    default: string
    description: string
}

export interface MessengerBridge {
    service: string
    label: string
    settings: MessengerBridgeParam[]
    params: MessengerBridgeParam[]
}

export interface ListenerConfig {
    url?: string
    // Write-only legacy field. Read responses expose presence only.
    token?: string
    token_configured?: boolean
    connection_key: string
}

export interface ConnectionParamDef {
    type: string
    required: boolean
    default: string
    description: string
    order?: number | null
}

export interface ConnectionSchema {
    params: Record<string, ConnectionParamDef>
}

export interface ToolGlobalParam {
    value: string | null
    configured: boolean
    secret: boolean
    forced: boolean
}

export interface ToolGlobalParamUpdate {
    value: string | null
    forced: boolean
    clear: boolean
}

export interface ToolGlobalParamsResponse {
    tool_id: number
    params: Record<string, ToolGlobalParam>
}

export interface TaskConfig {
    label?: string
    objective?: string
}

export interface Tool {
    id: number
    code: string
    label: string
    description: string
    has_mcp: boolean
    has_file_share: boolean
    has_messenger: boolean
    has_listener: boolean
    can_edit: boolean
    can_disable: boolean
    conversation_enabled: boolean
    mcp_config?: McpConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    connection_schema: ConnectionSchema
    global_params: Record<string, ToolGlobalParam>
    task_config?: TaskConfig | null
    created_at: string
    updated_at: string
}

export interface ToolCreate {
    code: string
    label: string
    description?: string
    mcp_config?: McpConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    connection_schema?: ConnectionSchema
    task_config?: TaskConfig | null
    conversation_enabled?: boolean
}

export interface ToolUpdate {
    label?: string
    description?: string
    mcp_config?: McpConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    connection_schema?: ConnectionSchema
    task_config?: TaskConfig | null
    conversation_enabled?: boolean
}

export interface ToolMcpTestRequest {
    tool_id?: number
    code: string
    mcp_config: McpConfig
    params: Record<string, string | null>
}

export interface ToolMcpTestFunction {
    name: string
    description: string
}

export type ToolMcpTestDiagnosticStage =
    | 'configuration'
    | 'dns'
    | 'tcp'
    | 'tls'
    | 'process'
    | 'authentication'
    | 'protocol'
    | 'discovery'

export type ToolMcpTestDiagnosticStatus =
    | 'success'
    | 'error'
    | 'warning'
    | 'skipped'
    | 'info'

export interface ToolMcpTestDiagnostic {
    stage: ToolMcpTestDiagnosticStage
    status: ToolMcpTestDiagnosticStatus
    message: string
    duration_ms: number | null
}

export interface ToolMcpTestResponse {
    success: boolean
    message: string
    failure_kind:
        | 'configuration'
        | 'dns'
        | 'tcp'
        | 'tls'
        | 'process'
        | 'authentication'
        | 'authorization'
        | 'endpoint'
        | 'protocol'
        | 'timeout'
        | 'server'
        | 'unknown'
        | null
    diagnostics: ToolMcpTestDiagnostic[]
    tools: ToolMcpTestFunction[]
}

// =============================================================================
// API
// =============================================================================

export interface ImportResult extends Tool {
    created: boolean
}

export default {
    getTools(): Promise<AxiosResponse<Tool[]>> {
        return api.get('/tools')
    },

    getFileShareBridges(): Promise<AxiosResponse<FileShareBridge[]>> {
        return api.get('/file-share/bridges')
    },

    getMessengerBridges(): Promise<AxiosResponse<MessengerBridge[]>> {
        return api.get('/messenger/bridges')
    },

    getTool(id: number): Promise<AxiosResponse<Tool>> {
        return api.get(`/tools/${id}`)
    },

    createTool(data: ToolCreate): Promise<AxiosResponse<Tool>> {
        return api.post('/tools', data)
    },

    updateTool(id: number, data: ToolUpdate): Promise<AxiosResponse<Tool>> {
        return api.put(`/tools/${id}`, data)
    },

    updateConversationAccess(id: number, enabled: boolean): Promise<AxiosResponse<Tool>> {
        return api.patch(`/tools/${id}/conversation-access`, { enabled })
    },

    getGlobalParams(id: number): Promise<AxiosResponse<ToolGlobalParamsResponse>> {
        return api.get(`/tools/${id}/global-params`)
    },

    updateGlobalParams(
        id: number,
        params: Record<string, ToolGlobalParamUpdate>,
    ): Promise<AxiosResponse<ToolGlobalParamsResponse>> {
        return api.put(`/tools/${id}/global-params`, { params })
    },

    testMcpConnection(data: ToolMcpTestRequest): Promise<AxiosResponse<ToolMcpTestResponse>> {
        return api.post('/tools/test-mcp', data)
    },

    deleteTool(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/tools/${id}`)
    },

    exportToolUrl(id: number): string {
        return `/api/tools/${id}/export`
    },

    importTool(yaml: string, overwrite = false): Promise<AxiosResponse<ImportResult>> {
        return api.post(`/tools/import?overwrite=${overwrite}`, yaml, {
            headers: { 'Content-Type': 'text/plain' },
        })
    },
}
