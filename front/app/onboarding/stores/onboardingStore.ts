import { toRaw } from 'vue'
import { withSessionScope } from '@/core/util/facade'
/**
 * Pinia store for onboarding state.
 *
 * This store tracks module configuration and determines whether onboarding
 * help blocks should be displayed on the home page.
 */
import { defineStore } from 'pinia'
import { sessionGeneration } from '@/core/api'
import onboardingService, {
  type OnboardingStatusResponse,
  type OnboardingOverviewResponse,
} from '../services/onboardingService'

export type { OnboardingStatusResponse, OnboardingOverviewResponse }

export const WELCOME_DISMISSAL_KEY = 'onboarding.welcome'

interface OnboardingState {
  languageConfigured: boolean | null
  llmProvider: OnboardingStatusResponse | null
  tools: OnboardingStatusResponse | null
  connections: OnboardingStatusResponse | null
  agents: OnboardingStatusResponse | null
  skills: OnboardingStatusResponse | null
  processes: OnboardingStatusResponse | null
  loading: boolean
  error: unknown
}

const reads = new WeakMap<object, symbol>()

export const useOnboardingStore = withSessionScope(defineStore('onboarding', {
  state: (): OnboardingState => ({
    languageConfigured: null,
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

    /** Whether the instance is missing a prerequisite for the guided mission. */
    instanceNeedsSetup: (state): boolean => {
      if (
        state.llmProvider === null
        || state.agents === null
      ) return false
      return (
        state.languageConfigured === false
        || !state.llmProvider.has_data
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
      const request = Symbol('overview'), session = sessionGeneration()
      reads.set(toRaw(this), request)
      const current = () => reads.get(toRaw(this)) === request && session === sessionGeneration()
      this.loading = true
      this.error = null
      try {
        const response = await onboardingService.getOverview()
        if (!current()) return
        this.$patch((state) => {
          state.languageConfigured = response.language_configured
          state.llmProvider = response.llm_provider
          state.tools = response.tools
          state.connections = response.connections
          state.agents = response.agents
          state.skills = response.skills
          state.processes = response.processes
        })
      } catch (error) {
        if (!current()) return
        this.error = error
        console.error('Error fetching onboarding overview:', error)
      } finally {
        if (current()) this.loading = false
      }
    },

    /**
     * Reset the store state.
     */
    clearState(): void {
      reads.delete(toRaw(this))
      this.$patch((state) => {
        state.languageConfigured = null
        state.llmProvider = null
        state.tools = null
        state.connections = null
        state.agents = null
        state.skills = null
        state.processes = null
        state.error = null
        state.loading = false
      })
    },
  },
}))
