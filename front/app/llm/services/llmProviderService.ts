import api from '@/core/api'
import type { AxiosResponse } from 'axios'

// =============================================================================
// LLM provider interfaces.
// =============================================================================

// Provider protocol identifiers are supplied by backend bridge profiles.
export type LLMProviderType = string
export type LLMProviderAuthType = 'api_key' | 'oauth_device' | 'optional_api_key'
export type AICapability =
    | 'chat'
    | 'vision'
    | 'image_generation'
    | 'embedding'
    | 'transcription'
    | 'speech'
    | 'realtime_conversation'
    | 'audio_understanding'
    | 'video_understanding'
    | 'sound_generation'
    | 'music_generation'
    | 'video_generation'
export type AIResourceType = 'model' | 'voice' | 'preset' | 'service'

export interface LLMProvider {
    id: number
    name: string
    catalog_code: string | null
    provider_type: LLMProviderType
    base_url: string
    transcription_base_url: string | null
    api_key_configured: boolean
    oauth_connected: boolean
    user_id: number | null
    subscription_acknowledged: boolean
    configuration: Record<string, unknown>
    is_custom: boolean
    is_active: boolean
    created_at: string
    updated_at: string | null
}

export interface LLMProviderDetail extends LLMProvider {
    api_key: string | null
}

export interface LLMProviderCreate {
    name: string
    catalog_code?: string | null
    provider_type?: LLMProviderType
    base_url: string
    transcription_base_url?: string | null
    api_key?: string | null
    configuration?: Record<string, unknown>
    is_active?: boolean
    user_id?: number | null
    subscription_acknowledged?: boolean
}

export interface LLMProviderUpdate {
    name?: string
    provider_type?: LLMProviderType
    base_url?: string
    transcription_base_url?: string | null
    api_key?: string | null
    configuration?: Record<string, unknown>
    is_active?: boolean
    user_id?: number | null
    subscription_acknowledged?: boolean
}

export interface LLMModelInfo {
    id: string
    name: string | null
    description: string | null
    context_length: number | null
    pricing: Record<string, unknown> | null
    modalities?: LLMModalities | null
    capabilities?: Record<string, boolean> | null
    release_date?: string | null
    status?: string | null
    metadata_source?: string | null
    resource_type: AIResourceType
    service_capabilities: AICapability[]
}

export interface ProviderCatalogConfigure {
    api_key?: string | null
    is_active: boolean
    configuration?: Record<string, unknown>
    user_id?: number | null
    subscription_acknowledged?: boolean
}

export interface ProviderUserOption {
    id: number
    label: string
}

export interface ProviderConfigurationField {
    key: string
    label: string
    required: boolean
    placeholder: string | null
}

export interface ProviderCatalogItem {
    key: string
    code: string | null
    display_name: string
    provider_type: LLMProviderType
    auth_type: LLMProviderAuthType
    default_base_url: string
    token_url: string | null
    documentation_url: string | null
    icon: string
    color: string
    api_key_required: boolean
    supports_transcription: boolean
    capabilities: AICapability[]
    configuration_fields: ProviderConfigurationField[]
    supports_model_management: boolean
    capability: AICapability
    is_custom: boolean
    connection: LLMProvider | null
}

export interface ProviderCatalogResponse {
    items: ProviderCatalogItem[]
    users: ProviderUserOption[]
    active_user_count: number
}

export interface LLMModelsListResponse {
    provider_id: number | null
    provider_name: string
    models: LLMModelInfo[]
    count: number
    supports_model_management: boolean
}

export interface ModelManageRequest {
    model_name: string
}

export interface ModelManageResponse {
    success: boolean
    message: string
    model_name: string
    provider_id: number
    provider_name: string
}

export interface LLMProviderTestRequest {
    configuration?: Record<string, unknown>
    provider_id?: number | null
    base_url: string
    api_key?: string | null
    provider_type?: LLMProviderType
    catalog_code?: string | null
}

export interface LLMProviderTestResponse {
    success: boolean
    message: string
    provider_name: string | null
    models_count: number | null
    error_details: string | null
}

export interface ProviderDeviceStartResponse {
    verification_uri: string
    user_code: string
    device_auth_id: string
    interval: number
    expires_in: number
}

export interface ProviderDevicePollResponse {
    status: 'pending' | 'connected'
    oauth_connected: boolean
}

// =============================================================================
// Configured LLM interfaces.
// =============================================================================

// Modalities supported by a model in each direction (input/output).
// Five modalities (text, image, file, video, audio) in two directions.
export interface LLMModalities {
    input_text: boolean
    input_image: boolean
    input_file: boolean
    input_video: boolean
    input_audio: boolean
    output_text: boolean
    output_image: boolean
    output_file: boolean
    output_video: boolean
    output_audio: boolean
}

export interface LLM extends LLMModalities {
    id: number
    llm_provider_id: number
    code: string
    llm_name: string
    label: string
    resource_type: AIResourceType
    primary_capability: AICapability
    service_capabilities: AICapability[]
    pricing: Record<string, unknown>
    context_length?: number | null
    cost_per_input_token?: number | null
    cost_per_cached_input_token?: number | null
    cost_per_output_token?: number | null
    is_subscription: boolean
    created_at: string
    updated_at: string | null
}

export interface LLMWithProvider extends LLM {
    provider_name: string
}

export interface LLMCreate extends Partial<LLMModalities> {
    llm_provider_id: number
    code: string
    llm_name: string
    label: string
    resource_type?: AIResourceType
    primary_capability?: AICapability
    service_capabilities?: AICapability[]
    pricing?: Record<string, unknown>
    context_length?: number | null
    cost_per_input_token?: number | null
    cost_per_cached_input_token?: number | null
    cost_per_output_token?: number | null
    is_subscription?: boolean
}

export interface LLMUpdate extends Partial<LLMModalities> {
    llm_provider_id?: number
    code?: string | null
    llm_name?: string
    label?: string
    resource_type?: AIResourceType
    primary_capability?: AICapability
    service_capabilities?: AICapability[]
    pricing?: Record<string, unknown>
    context_length?: number | null
    cost_per_input_token?: number | null
    cost_per_cached_input_token?: number | null
    cost_per_output_token?: number | null
    is_subscription?: boolean
}

// Metadata returned by the normalized model-metadata endpoint.
export interface LLMModelMeta {
    cost_per_input_token: number | null
    cost_per_cached_input_token: number | null
    cost_per_output_token: number | null
    context_length?: number | null
    modalities?: LLMModalities | null
}

// =============================================================================
// Service
// =============================================================================

export default {
    // -------------------------------------------------------------------------
    // CRUD Operations
    // -------------------------------------------------------------------------

    getProviders(active_only?: boolean): Promise<AxiosResponse<LLMProvider[]>> {
        const params: Record<string, unknown> = {}
        if (active_only !== undefined) params.active_only = active_only
        return api.get('/llm-providers', { params })
    },

    getProviderCatalog(): Promise<AxiosResponse<ProviderCatalogResponse>> {
        return api.get('/llm-providers/catalog')
    },

    configureCatalogProvider(
        code: string,
        data: ProviderCatalogConfigure
    ): Promise<AxiosResponse<LLMProvider>> {
        return api.put(`/llm-providers/catalog/${encodeURIComponent(code)}`, data)
    },

    getProvider(id: number): Promise<AxiosResponse<LLMProviderDetail>> {
        return api.get(`/llm-providers/${id}`)
    },

    createProvider(data: LLMProviderCreate): Promise<AxiosResponse<LLMProvider>> {
        return api.post('/llm-providers', data)
    },

    updateProvider(id: number, data: LLMProviderUpdate): Promise<AxiosResponse<LLMProvider>> {
        return api.put(`/llm-providers/${id}`, data)
    },

    deleteProvider(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/llm-providers/${id}`)
    },

    startProviderDeviceLogin(id: number): Promise<AxiosResponse<ProviderDeviceStartResponse>> {
        return api.post(`/llm-providers/${id}/oauth/device`)
    },

    pollProviderDeviceLogin(
        id: number,
        data: { device_auth_id: string; user_code: string }
    ): Promise<AxiosResponse<ProviderDevicePollResponse>> {
        return api.post(`/llm-providers/${id}/oauth/device/poll`, data)
    },

    disconnectProviderAuthentication(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/llm-providers/${id}/oauth`)
    },

    // -------------------------------------------------------------------------
    // LLM models.
    // -------------------------------------------------------------------------

    getProviderModels(id: number, refresh = false): Promise<AxiosResponse<LLMModelsListResponse>> {
        return api.get(`/llm-providers/${id}/models`, { params: refresh ? { refresh: true } : {} })
    },

    getProviderResources(
        id: number,
        capability: AICapability,
        refresh = false,
    ): Promise<AxiosResponse<LLMModelsListResponse>> {
        return api.get(`/llm-providers/${id}/resources`, {
            params: { capability, ...(refresh ? { refresh: true } : {}) },
        })
    },

    getCatalogResources(
        code: string,
        capability: AICapability,
        refresh = false,
    ): Promise<AxiosResponse<LLMModelsListResponse>> {
        return api.get(`/llm-providers/catalog/${encodeURIComponent(code)}/resources`, {
            params: { capability, ...(refresh ? { refresh: true } : {}) },
        })
    },

    // Transcription models use transcription_base_url when configured, otherwise
    // base_url results are filtered by name. Returned models are flagged as audio input.
    getProviderTranscriptionModels(id: number): Promise<AxiosResponse<LLMModelsListResponse>> {
        return api.get(`/llm-providers/${id}/transcription-models`)
    },

    // -------------------------------------------------------------------------
    // Client-side LLM availability checks.
    // -------------------------------------------------------------------------

    async checkLLMAvailability(
        providerId: number,
        llmName: string,
        capability: AICapability = 'chat',
    ): Promise<boolean> {
        try {
            const response = await this.getProviderResources(providerId, capability)
            const availableModels = response.data.models
            return availableModels.some(model => model.id === llmName)
        } catch (error) {
            console.error('Error checking LLM availability:', error)
            return false
        }
    },

    // -------------------------------------------------------------------------
    // Connection test.
    // -------------------------------------------------------------------------

    testConnection(data: LLMProviderTestRequest): Promise<AxiosResponse<LLMProviderTestResponse>> {
        return api.post('/llm-providers/test', data)
    },

    // -------------------------------------------------------------------------
    // Model management for providers supporting pull/delete operations.
    // -------------------------------------------------------------------------

    pullModel(providerId: number, modelName: string): Promise<AxiosResponse<ModelManageResponse>> {
        return api.post(`/llm-providers/${providerId}/models/pull`, { model_name: modelName })
    },

    deleteModel(providerId: number, modelName: string): Promise<AxiosResponse<ModelManageResponse>> {
        return api.post(`/llm-providers/${providerId}/models/delete`, { model_name: modelName })
    },

    // -------------------------------------------------------------------------
    // Configured LLM CRUD operations.
    // -------------------------------------------------------------------------

    getLLMs(provider_id?: number): Promise<AxiosResponse<LLMWithProvider[]>> {
        const config: { params?: Record<string, unknown> } = {}
        if (provider_id !== undefined && provider_id !== null) {
            config.params = { provider_id }
        }
        return api.get('/llm-providers/llms', config)
    },

    getLLM(id: number): Promise<AxiosResponse<LLMWithProvider>> {
        return api.get(`/llm-providers/llms/${id}`)
    },

    createLLM(data: LLMCreate): Promise<AxiosResponse<LLM>> {
        return api.post('/llm-providers/llms', data)
    },

    updateLLM(id: number, data: LLMUpdate): Promise<AxiosResponse<LLM>> {
        return api.put(`/llm-providers/llms/${id}`, data)
    },

    deleteLLM(id: number): Promise<AxiosResponse<void>> {
        return api.delete(`/llm-providers/llms/${id}`)
    },

    // -------------------------------------------------------------------------
    // Normalized model metadata retrieval.
    // -------------------------------------------------------------------------

    async fetchModelMetadata(modelId: string): Promise<LLMModelMeta> {
        try {
            // Ask the backend for normalized pricing and modality metadata.
            const response = await api.post('/llm-providers/fetch-pricing', { model_id: modelId })
            return response.data
        } catch (error) {
            // Return empty defaults when pricing lookup fails.
            return {
                cost_per_input_token: null,
                cost_per_cached_input_token: null,
                cost_per_output_token: null,
                modalities: null,
            }
        }
    },
}
