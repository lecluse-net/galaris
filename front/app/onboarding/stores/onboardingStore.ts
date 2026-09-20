/**
 * Pinia store for onboarding state.
 *
 * This store tracks module configuration and determines whether onboarding
 * help blocks should be displayed on the home page.
 */
import { defineStore } from 'pinia'
import onboardingService, {
  type OnboardingStatusResponse,
  type OnboardingOverviewResponse,
} from '../services/onboardingService'

export type { OnboardingStatusResponse, OnboardingOverviewResponse }

interface OnboardingState {
  llmProvider: OnboardingStatusResponse | null
  tools: OnboardingStatusResponse | null
  connections: OnboardingStatusResponse | null
  agents: OnboardingStatusResponse | null
  skills: OnboardingStatusResponse | null
  processes: OnboardingStatusResponse | null
  loading: boolean
  error: unknown
}

export const useOnboardingStore = defineStore('onboarding', {
  state: (): OnboardingState => ({
    llmProvider: null,
    tools: null,
    connections: null,
    agents: null,
    skills: null,
    processes: null,
    loading: false,
    error: null,
  }),

  getters: {
    /**
     * Whether the LLM provider block should be displayed.
     */
    showLLMProviderBlock: (state): boolean => {
      return state.llmProvider?.show ?? false
    },

    /**
     * Whether the tools block should be displayed.
     */
    showToolsBlock: (state): boolean => {
      return state.tools?.show ?? false
    },

    /**
     * Whether the connections block should be displayed.
     */
    showConnectionsBlock: (state): boolean => {
      return state.connections?.show ?? false
    },

    /**
     * Whether the agents block should be displayed.
     */
    showAgentsBlock: (state): boolean => {
      return state.agents?.show ?? false
    },

    skillsAccess: (state): boolean => state.skills?.has_privilege ?? false,

    processesAccess: (state): boolean => state.processes?.has_privilege ?? false,

    /**
     * Whether at least one onboarding block should be displayed.
     */
    hasAnyOnboardingBlock: (state): boolean => {
      return (
        (state.llmProvider?.show ?? false) ||
        (state.tools?.show ?? false) ||
        (state.connections?.show ?? false) ||
        (state.agents?.show ?? false)
      )
    },

    /**
     * Whether the initial setup must replace the authenticated home page.
     *
     * This is intentionally based on data rather than privileges: a user who
     * cannot edit the missing resource still needs to understand why the
     * instance is not ready.
     */
    needsInitialSetup: (state): boolean => {
      if (
        state.llmProvider === null
        || state.agents === null
      ) return false
      return (
        !state.llmProvider.has_data
        || !state.agents.has_data
      )
    },

    /**
     * Return whether the onboarding data has been loaded.
     */
    isLoaded: (state): boolean => {
      return state.llmProvider !== null
    },
  },

  actions: {
    /**
     * Fetch onboarding state for every module.
     */
    async fetchOverview(): Promise<void> {
      this.loading = true
      this.error = null
      try {
        const response = await onboardingService.getOverview()
        this.$patch((state) => {
          state.llmProvider = response.llm_provider
          state.tools = response.tools
          state.connections = response.connections
          state.agents = response.agents
          state.skills = response.skills
          state.processes = response.processes
        })
      } catch (error) {
        this.error = error
        console.error('Error fetching onboarding overview:', error)
      } finally {
        this.loading = false
      }
    },

    /**
     * Reset the store state.
     */
    clearState(): void {
      this.$patch((state) => {
        state.llmProvider = null
        state.tools = null
        state.connections = null
        state.agents = null
        state.skills = null
        state.processes = null
        state.error = null
      })
    },
  },
})
