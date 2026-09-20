import { defineStore } from 'pinia'
import {
    paramsService,
    type ParamItem,
    type ParamUpdate,
    type PromptAction,
} from '../services/paramsService'

interface ParamsState {
    params: ParamItem[]
    loading: boolean
    error: unknown
}

export const useParamsStore = defineStore('params', {
    state: (): ParamsState => ({
        params: [],
        loading: false,
        error: null
    }),

    getters: {
        /**
         * Return parameters sorted by name.
         */
        sortedParams: (state): ParamItem[] => {
            return [...state.params].sort((a, b) => a.name.localeCompare(b.name))
        },

        /**
         * Return a parameter by name.
         */
        getParamByName: (state) => (name: string): ParamItem | undefined => {
            return state.params.find(p => p.name === name)
        },

        /**
         * Return a parameter value.
         */
        getParamValue: (state) => (name: string): string | null => {
            const param = state.params.find(p => p.name === name)
            return param?.value ?? null
        }
    },

    actions: {
        /**
         * Load all parameters from the backend.
         */
        async fetchParams(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await paramsService.getParamsList()
                this.params = response.data.params
            } catch (error) {
                this.error = error
                console.error('Error fetching params:', error)
            } finally {
                this.loading = false
            }
        },

        /**
         * Update a parameter value.
         * @param name Parameter name.
         * @param value New value.
         */
        async updateParam(
            name: string,
            value: string | null,
            clearSecret = false,
            promptAction?: PromptAction,
        ): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const update: ParamUpdate = {
                    value,
                    clear_secret: clearSecret,
                    prompt_action: promptAction,
                }
                const response = await paramsService.updateParam(name, update)
                // Update local state after a successful request.
                const param = this.params.find(p => p.name === name)
                if (param) {
                    param.value = response.data.value
                    param.secret = response.data.secret
                    param.configured = response.data.configured
                    param.prompt = response.data.prompt
                }
            } catch (error) {
                this.error = error
                console.error(`Error updating param ${name}:`, error)
                throw error
            } finally {
                this.loading = false
            }
        }
    }
})
