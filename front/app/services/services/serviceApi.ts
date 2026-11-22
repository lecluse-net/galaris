import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface ServiceIcon {
    media_type: 'image/svg+xml' | 'image/png' | 'image/gif'
    encoding: 'text' | 'base64'
    data: string
}
export interface ServiceCatalogMetadata {
    format_version: number
    version: string
    minimum_galaris_version: string
    summary: Record<string, string>
    documentation: string
    icon_credit: string
    plugin_code?: string | null
    plugin_version?: string | null
}
export interface ServicePreset {
    definition: ServiceCreate
    compatible: boolean
    compatibility: 'supported' | 'format' | 'version' | 'protocol'
}
export interface ServiceCatalog {
    source: 'bundled' | 'github'
    revision: string
    entries: ServicePreset[]
    refresh_failed: boolean
}

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

export interface RestConfig {
    base_url: string
    auth: {
        type: 'none' | 'bearer' | 'header' | 'basic' | 'query'
        param: string
        header_name: string
        query_name: string
        login_param: string
        password_param: string
    }
    header_params: Record<string, string>
    timeout: number
    max_response_bytes: number
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
    // Server-level bridge values shared by every connection to this Service.
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

export interface ConnectionParamOption {
    value: string
    label: string
}

export interface ConnectionParamDef {
    type: string
    widget?: string
    required: boolean
    default: string
    description: string
    order?: number | null
    label?: string
    builtin?: boolean
    options?: ConnectionParamOption[]
}

export interface ConnectionSchema {
    params: Record<string, ConnectionParamDef>
}

export interface ServiceGlobalParam {
    value: string | null
    configured: boolean
    secret: boolean
    forced: boolean
}

export interface ServiceGlobalParamUpdate {
    value: string | null
    forced: boolean
    clear: boolean
}

export interface ServiceGlobalParamsResponse {
    service_id: number
    params: Record<string, ServiceGlobalParam>
}

export interface TaskConfig {
    label?: string
    objective?: string
}

export interface CapabilityProtocol {
    value: string
    capability: string
    label: string
    builtin: boolean
    parameters?: Record<string, ConnectionParamDef & { section?: string }>
    connection_parameters?: Record<string, { parameter: string; legacy_parameter?: string; label: string; section?: string; definition: ConnectionParamDef }>
}

export interface ProtocolConfig { settings?: Record<string, string>; param_map?: Record<string, string> }

export interface CapabilityDefinition {
    code: string
    label: string
    builtin: boolean
    protocols: CapabilityProtocol[]
}

export interface Service {
    /** Present in list responses; includes inactive connections. */
    connection_count?: number
    icon?: ServiceIcon | null
    catalog?: ServiceCatalogMetadata | null
    capabilities?: string[]
    id: number
    code: string
    label: string
    description: string
    has_mcp: boolean
    has_function_permissions?: boolean
    has_api: boolean
    rest_config?: RestConfig | null
    has_file_share: boolean
    has_messenger: boolean
    has_listener: boolean
    has_mail?: boolean
    has_calendar?: boolean
    can_edit: boolean
    can_disable: boolean
    mcp_config?: McpConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    mail_config?: ProtocolConfig | null
    calendar_config?: ProtocolConfig | null
    connection_schema: ConnectionSchema
    global_params: Record<string, ServiceGlobalParam>
    task_config?: TaskConfig | null
    created_at: string
    updated_at: string
}

export interface ServiceCreate {
    icon?: ServiceIcon | null
    catalog?: ServiceCatalogMetadata | null
    capabilities?: string[]
    code: string
    label: string
    description?: string
    mcp_config?: McpConfig | null
    rest_config?: RestConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    mail_config?: ProtocolConfig | null
    calendar_config?: ProtocolConfig | null
    connection_schema?: ConnectionSchema
    task_config?: TaskConfig | null
}

export interface ServiceUpdate {
    icon?: ServiceIcon | null
    catalog?: ServiceCatalogMetadata | null
    capabilities?: string[]
    label?: string
    description?: string
    mcp_config?: McpConfig | null
    rest_config?: RestConfig | null
    file_share_config?: FileShareConfig | null
    messenger_config?: MessengerConfig | null
    listener_config?: ListenerConfig | null
    mail_config?: ProtocolConfig | null
    calendar_config?: ProtocolConfig | null
    connection_schema?: ConnectionSchema
    task_config?: TaskConfig | null
}

export interface ServiceMcpTestRequest {
    service_id?: number
    code: string
    mcp_config: McpConfig
    params: Record<string, string | null>
}

export interface ServiceMcpTestFunction {
    name: string
    description: string
}

export type ServiceMcpTestDiagnosticStage =
    | 'configuration'
    | 'dns'
    | 'tcp'
    | 'tls'
    | 'process'
    | 'authentication'
    | 'protocol'
    | 'discovery'

export type ServiceMcpTestDiagnosticStatus =
    | 'success'
    | 'error'
    | 'warning'
    | 'skipped'
    | 'info'

export interface ServiceMcpTestDiagnostic {
    stage: ServiceMcpTestDiagnosticStage
    status: ServiceMcpTestDiagnosticStatus
    message: string
    duration_ms: number | null
}

export interface ServiceMcpTestResponse {
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
    diagnostics: ServiceMcpTestDiagnostic[]
    tools: ServiceMcpTestFunction[]
}

// =============================================================================
// API
// =============================================================================

export interface ImportResult extends Service {
    created: boolean
}

export interface ServiceDeletionImpact {
    service_id: number
    version: string
    deleted: { kind: 'connections' | 'parameters' | 'authorizations' | 'accounts' | 'messaging' | 'processes' | 'fileIndex' | 'workspaces' | 'other'; count: number }[]
    detached_count: number
}

export interface ConversationToolEntry {
    name: string
    source: 'native' | 'external'
    enabled: boolean
}

export interface ConversationToolCatalog {
    tools: ConversationToolEntry[]
    discovery_incomplete: boolean
    next_connection_id: number | null
}

export type InventoryToolState = 'enabled' | 'disabled' | 'ask'

export interface InventoryTool {
    name: string
    conversation_enabled: boolean
    default_state: InventoryToolState
    service_override: InventoryToolState | null
}

export interface ServiceToolInventory {
    code: string
    label: string
    icon: ServiceIcon | null
    connection_default: 'active' | 'inactive' | 'manual'
    connection_schema: ConnectionSchema
    global_params: Record<string, ServiceGlobalParam>
    tools: InventoryTool[]
}

export default {
    getToolInventory(signal: AbortSignal): Promise<AxiosResponse<ServiceToolInventory[]>> {
        return api.get('/services/tool-inventory', { signal })
    },

    getConversationTools(id: number, discover: boolean, signal: AbortSignal, afterConnectionId?: number): Promise<AxiosResponse<ConversationToolCatalog>> {
        const path = `/services/${id}/conversation-tools`
        return discover
            ? api.post(`${path}/discover`, undefined, { signal, params: { after_connection_id: afterConnectionId } })
            : api.get(path, { signal })
    },

    setConversationTool(id: number, tool: ConversationToolEntry): Promise<AxiosResponse<{ enabled: boolean }>> {
        return api.patch(`/services/${id}/conversation-tools`, tool)
    },
    getCatalog(): Promise<AxiosResponse<ServiceCatalog>> {
        return api.get('/services/catalog')
    },
    refreshCatalog(): Promise<AxiosResponse<ServiceCatalog>> {
        return api.post('/services/catalog/refresh')
    },
    getServices(signal?: AbortSignal): Promise<AxiosResponse<Service[]>> {
        return api.get('/services', { signal })
    },

    getCapabilities(): Promise<AxiosResponse<CapabilityDefinition[]>> {
        return api.get('/services/capabilities')
    },

    getFileShareBridges(): Promise<AxiosResponse<FileShareBridge[]>> {
        return api.get('/file-share/bridges')
    },

    getMessengerBridges(): Promise<AxiosResponse<MessengerBridge[]>> {
        return api.get('/messenger/bridges')
    },

    getService(id: number): Promise<AxiosResponse<Service>> {
        return api.get(`/services/${id}`)
    },

    createService(data: ServiceCreate): Promise<AxiosResponse<Service>> {
        return api.post('/services', data)
    },

    updateService(id: number, data: ServiceUpdate): Promise<AxiosResponse<Service>> {
        return api.put(`/services/${id}`, data)
    },

    getGlobalParams(id: number): Promise<AxiosResponse<ServiceGlobalParamsResponse>> {
        return api.get(`/services/${id}/global-params`)
    },

    updateGlobalParams(
        id: number,
        params: Record<string, ServiceGlobalParamUpdate>,
    ): Promise<AxiosResponse<ServiceGlobalParamsResponse>> {
        return api.put(`/services/${id}/global-params`, { params })
    },

    testMcpConnection(data: ServiceMcpTestRequest): Promise<AxiosResponse<ServiceMcpTestResponse>> {
        return api.post('/services/test-mcp', data)
    },

    prepareMcpCandidate(agentId: number, definition: ServiceCreate, params: Record<string, string | null>): Promise<AxiosResponse<{ reference: string; expires_in_seconds: number }>> {
        return api.post('/services/mcp-candidates', { agent_id: agentId, definition, params })
    },

    getDeletionImpact(id: number): Promise<AxiosResponse<ServiceDeletionImpact>> {
        return api.get(`/services/${id}/deletion-impact`)
    },

    deleteService(id: number, confirmationVersion?: string): Promise<AxiosResponse<void>> {
        return api.delete(`/services/${id}`, confirmationVersion
            ? { params: { cascade: true, expected_version: confirmationVersion } } : undefined)
    },

    exportServiceUrl(id: number): string {
        return `/api/services/${id}/export`
    },

    importService(yaml: string, overwrite = false): Promise<AxiosResponse<ImportResult>> {
        return api.post(`/services/import?overwrite=${overwrite}`, yaml, {
            headers: { 'Content-Type': 'text/plain' },
        })
    },
}
