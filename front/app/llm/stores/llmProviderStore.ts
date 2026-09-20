import { defineStore } from 'pinia'
import llmProviderService, {
    type LLMProviderCreate,
    type LLMProviderUpdate,
    type LLMModelsListResponse,
    type LLMProviderTestRequest,
    type LLMProviderTestResponse,
    type LLMCreate,
    type LLMUpdate,
    type LLM,
    type LLMWithProvider,
    type ModelManageResponse,
    type ProviderDeviceStartResponse,
    type ProviderDevicePollResponse,
    type ProviderCatalogItem,
    type ProviderCatalogConfigure,
    type AICapability,
    type ProviderUserOption,
} from '../services/llmProviderService'
import type { LLMProvider, LLMProviderDetail, LLMModelInfo, LLMProviderType } from '../services/llmProviderService'

export type { LLMProvider, LLMProviderDetail, LLMModelInfo, LLMProviderType, LLMModelsListResponse, LLMProviderTestResponse, LLM, LLMWithProvider, ModelManageResponse, ProviderDeviceStartResponse, ProviderDevicePollResponse, ProviderCatalogItem, ProviderCatalogConfigure }

interface LLMProviderState {
    providers: LLMProvider[]
    catalogItems: ProviderCatalogItem[]
    providerUsers: ProviderUserOption[]
    activeUserCount: number
    currentProvider: LLMProviderDetail | null
    currentProviderModels: LLMModelInfo[]
    llms: LLMWithProvider[]
    currentLLM: LLMWithProvider | null
    loading: boolean
    loadingModels: boolean
    loadingLLMs: boolean
    error: unknown
}

export const useLLMProviderStore = defineStore('llmProvider', {
    state: (): LLMProviderState => ({
        providers: [],
        catalogItems: [],
        providerUsers: [],
        activeUserCount: 0,
        currentProvider: null,
        currentProviderModels: [],
        llms: [],
        currentLLM: null,
        loading: false,
        loadingModels: false,
        loadingLLMs: false,
        error: null
    }),

    getters: {
        activeProviders: (state): LLMProvider[] => {
            return state.providers.filter(p => p.is_active)
        },

        getProviderById: (state) => (id: number): LLMProvider | undefined => {
            return state.providers.find(p => p.id === id)
        },

        activeCatalogItems: (state): ProviderCatalogItem[] => {
            return state.catalogItems.filter(item => item.connection?.is_active)
        },

        availableCatalogItems: (state): ProviderCatalogItem[] => {
            return state.catalogItems.filter(item => !item.connection?.is_active)
        },
    },

    actions: {
        // =====================================================================
        // CRUD Operations
        // =====================================================================

        async fetchProviders(activeOnly?: boolean): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.getProviders(activeOnly)
                this.providers = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching LLM providers:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async fetchCatalog(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.getProviderCatalog()
                this.catalogItems = response.data.items
                this.providerUsers = response.data.users
                this.activeUserCount = response.data.active_user_count
            } catch (error) {
                this.error = error
                console.error('Error fetching LLM provider catalog:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async refreshProviders(): Promise<void> {
            await Promise.all([this.fetchProviders(), this.fetchCatalog()])
        },

        async configureCatalogProvider(
            code: string,
            configuration: ProviderCatalogConfigure
        ): Promise<LLMProvider> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.configureCatalogProvider(code, configuration)
                await Promise.all([this.fetchProviders(), this.fetchCatalog()])
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error configuring catalog provider:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async fetchProvider(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.getProvider(id)
                this.currentProvider = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching LLM provider:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async createProvider(provider: LLMProviderCreate): Promise<LLMProvider> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.createProvider(provider)
                this.providers.push(response.data)
                await this.fetchCatalog()
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating LLM provider:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async updateProvider(id: number, provider: LLMProviderUpdate): Promise<LLMProvider> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.updateProvider(id, provider)
                const index = this.providers.findIndex(p => p.id === id)
                if (index !== -1) {
                    this.providers[index] = response.data
                }
                if (this.currentProvider?.id === id) {
                    // Update only non-sensitive fields.
                    this.currentProvider = {
                        ...this.currentProvider,
                        ...response.data
                    } as LLMProviderDetail
                }
                await this.fetchCatalog()
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating LLM provider:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async deleteProvider(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await llmProviderService.deleteProvider(id)
                this.providers = this.providers.filter(p => p.id !== id)
                if (this.currentProvider?.id === id) {
                    this.currentProvider = null
                }
                await this.fetchCatalog()
            } catch (error) {
                this.error = error
                console.error('Error deleting LLM provider:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async startProviderDeviceLogin(id: number): Promise<ProviderDeviceStartResponse> {
            const response = await llmProviderService.startProviderDeviceLogin(id)
            return response.data
        },

        async pollProviderDeviceLogin(
            id: number,
            challenge: ProviderDeviceStartResponse
        ): Promise<ProviderDevicePollResponse> {
            const response = await llmProviderService.pollProviderDeviceLogin(id, {
                device_auth_id: challenge.device_auth_id,
                user_code: challenge.user_code,
            })
            if (response.data.oauth_connected) {
                const provider = this.providers.find(item => item.id === id)
                if (provider) provider.oauth_connected = true
            }
            return response.data
        },

        async disconnectProviderAuthentication(id: number): Promise<void> {
            await llmProviderService.disconnectProviderAuthentication(id)
            const provider = this.providers.find(item => item.id === id)
            if (provider) provider.oauth_connected = false
        },

        // =====================================================================
        // LLM models.
        // =====================================================================

        async fetchProviderModels(id: number, refresh = false): Promise<LLMModelsListResponse> {
            this.loadingModels = true
            this.error = null
            try {
                const response = await llmProviderService.getProviderModels(id, refresh)
                this.currentProviderModels = response.data.models
                return response.data
            } catch (error) {
                this.error = error
                this.currentProviderModels = []
                console.error('Error fetching provider models:', error)
                throw error
            } finally {
                this.loadingModels = false
            }
        },

        async fetchProviderResources(
            id: number,
            capability: AICapability,
            refresh = false,
        ): Promise<LLMModelsListResponse> {
            this.loadingModels = true
            this.error = null
            try {
                const response = await llmProviderService.getProviderResources(id, capability, refresh)
                this.currentProviderModels = response.data.models
                return response.data
            } catch (error) {
                this.error = error
                this.currentProviderModels = []
                console.error('Error fetching provider AI resources:', error)
                throw error
            } finally {
                this.loadingModels = false
            }
        },

        async fetchCatalogResources(
            code: string,
            capability: AICapability,
            refresh = false,
        ): Promise<LLMModelsListResponse> {
            this.loadingModels = true
            this.error = null
            try {
                const response = await llmProviderService.getCatalogResources(code, capability, refresh)
                this.currentProviderModels = response.data.models
                return response.data
            } catch (error) {
                this.error = error
                this.currentProviderModels = []
                console.error('Error fetching public provider resources:', error)
                throw error
            } finally {
                this.loadingModels = false
            }
        },

        async fetchProviderTranscriptionModels(id: number): Promise<LLMModelsListResponse> {
            this.loadingModels = true
            this.error = null
            try {
                const response = await llmProviderService.getProviderTranscriptionModels(id)
                this.currentProviderModels = response.data.models
                return response.data
            } catch (error) {
                this.error = error
                this.currentProviderModels = []
                console.error('Error fetching transcription models:', error)
                throw error
            } finally {
                this.loadingModels = false
            }
        },

        clearCurrentProvider(): void {
            this.currentProvider = null
            this.currentProviderModels = []
        },

        clearError(): void {
            this.error = null
        },

        // =====================================================================
        // Connection test.
        // =====================================================================

        async testConnection(data: LLMProviderTestRequest): Promise<LLMProviderTestResponse> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.testConnection(data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error testing LLM provider connection:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // =====================================================================
        // Configured LLM CRUD operations.
        // =====================================================================

        async fetchLLMs(providerId?: number): Promise<void> {
            this.loadingLLMs = true
            this.error = null
            try {
                // Omit an undefined providerId to avoid a 422 response.
                const response = providerId !== undefined
                    ? await llmProviderService.getLLMs(providerId)
                    : await llmProviderService.getLLMs()
                this.llms = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching LLMs:', error)
                throw error
            } finally {
                this.loadingLLMs = false
            }
        },

        async fetchLLM(id: number): Promise<void> {
            this.loadingLLMs = true
            this.error = null
            try {
                const response = await llmProviderService.getLLM(id)
                this.currentLLM = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching LLM:', error)
                throw error
            } finally {
                this.loadingLLMs = false
            }
        },

        async createLLM(llm: LLMCreate): Promise<LLM> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.createLLM(llm)
                // Reload the complete list to refresh provider_name values.
                await this.fetchLLMs()
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating LLM:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async updateLLM(id: number, llm: LLMUpdate): Promise<LLM> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.updateLLM(id, llm)
                const index = this.llms.findIndex(l => l.id === id)
                if (index !== -1) {
                    // Apply new data while preserving provider_name.
                    this.llms[index] = {
                        ...this.llms[index],
                        ...response.data
                    } as LLMWithProvider
                }
                if (this.currentLLM?.id === id) {
                    this.currentLLM = {
                        ...this.currentLLM,
                        ...response.data
                    } as LLMWithProvider
                }
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating LLM:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async deleteLLM(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await llmProviderService.deleteLLM(id)
                this.llms = this.llms.filter(l => l.id !== id)
                if (this.currentLLM?.id === id) {
                    this.currentLLM = null
                }
            } catch (error) {
                this.error = error
                console.error('Error deleting LLM:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        clearCurrentLLM(): void {
            this.currentLLM = null
        },

        // =====================================================================
        // Client-side LLM availability checks.
        // =====================================================================

        async checkLLMAvailability(llm: LLMWithProvider): Promise<boolean> {
            try {
                const isAvailable = await llmProviderService.checkLLMAvailability(
                    llm.llm_provider_id,
                    llm.llm_name,
                    llm.primary_capability,
                )
                return isAvailable
            } catch (error) {
                console.error('Error checking LLM availability:', error)
                return false
            }
        },

        async checkAllLLMs(): Promise<Map<number, boolean>> {
            const availabilityMap = new Map<number, boolean>()
            
            for (const llm of this.llms) {
                const isAvailable = await this.checkLLMAvailability(llm)
                availabilityMap.set(llm.id, isAvailable)
            }
            
            return availabilityMap
        },

        // =====================================================================
        // Provider model management (pull/delete).
        // =====================================================================

        async pullModel(providerId: number, modelName: string): Promise<ModelManageResponse> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.pullModel(providerId, modelName)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error pulling model:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async deleteModel(providerId: number, modelName: string): Promise<ModelManageResponse> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProviderService.deleteModel(providerId, modelName)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error deleting model:', error)
                throw error
            } finally {
                this.loading = false
            }
        },
    }
})
