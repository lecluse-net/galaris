import { defineStore } from 'pinia'
import llmProfileService, {
    type LlmProfile,
    type LlmProfileCreate,
    type LlmProfileUpdate,
    type LlmProfileUseResponse,
} from '../services/llmProfileService'

export type { LlmProfile, LlmProfileCreate, LlmProfileUpdate, LlmProfileUseResponse }

interface LLMProfileState {
    profiles: LlmProfile[]
    // Id of the profile currently active for the agents (global parameter).
    currentProfileId: number | null
    loading: boolean
    applying: boolean
    error: unknown
}

export const useLLMProfileStore = defineStore('llmProfile', {
    state: (): LLMProfileState => ({
        profiles: [],
        currentProfileId: null,
        loading: false,
        applying: false,
        error: null
    }),

    getters: {
        getProfileById: (state) => (id: number): LlmProfile | undefined => {
            return state.profiles.find(p => p.id === id)
        },

        currentProfile: (state): LlmProfile | undefined => {
            if (state.currentProfileId === null) {
                return undefined
            }
            return state.profiles.find(p => p.id === state.currentProfileId)
        },

        profileLabels: (state): string[] => {
            return state.profiles.map(p => p.label)
        },
    },

    actions: {
        // =====================================================================
        // CRUD operations.
        // =====================================================================

        async fetchProfiles(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProfileService.getProfiles()
                this.profiles = response.data.profiles
                this.currentProfileId = response.data.current_profile_id
            } catch (error) {
                this.error = error
                console.error('Error fetching LLM profiles:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // Refreshes a single profile in place from its own editing response.
        upsertProfile(profile: LlmProfile): void {
            const index = this.profiles.findIndex(p => p.id === profile.id)
            if (index !== -1) {
                this.profiles[index] = profile
            } else {
                this.profiles.push(profile)
            }
        },

        async createProfile(data: LlmProfileCreate): Promise<LlmProfile> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProfileService.createProfile(data)
                this.profiles.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating LLM profile:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async updateProfile(id: number, data: LlmProfileUpdate): Promise<LlmProfile> {
            this.loading = true
            this.error = null
            try {
                const response = await llmProfileService.updateProfile(id, data)
                this.upsertProfile(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating LLM profile:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // Silent variant used by the usage-page grid: persists the displayed
        // profile's column without flipping the banner loading flag.
        async saveProfileValues(id: number, data: LlmProfileUpdate): Promise<LlmProfile> {
            this.error = null
            try {
                const response = await llmProfileService.updateProfile(id, data)
                this.upsertProfile(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error saving LLM profile values:', error)
                throw error
            }
        },

        async deleteProfile(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                await llmProfileService.deleteProfile(id)
                this.profiles = this.profiles.filter(p => p.id !== id)
            } catch (error) {
                this.error = error
                console.error('Error deleting LLM profile:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // =====================================================================
        // Profile use: sets the current-profile pointer only, nothing is copied.
        // =====================================================================

        async useProfile(id: number): Promise<LlmProfileUseResponse> {
            this.applying = true
            this.error = null
            try {
                const response = await llmProfileService.useProfile(id)
                this.currentProfileId = response.data.current_profile_id
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error using LLM profile:', error)
                throw error
            } finally {
                this.applying = false
            }
        },

        clearError(): void {
            this.error = null
        },
    }
})
