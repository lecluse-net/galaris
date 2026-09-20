import { defineStore } from 'pinia'
import toolService, { type Tool, type ToolCreate, type ToolUpdate } from '../services/toolService'

interface ToolState {
    tools: Tool[]
    loading: boolean
    error: unknown
}

export const useToolStore = defineStore('tool', {
    state: (): ToolState => ({
        tools: [],
        loading: false,
        error: null,
    }),

    actions: {
        async fetchTools(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await toolService.getTools()
                this.tools = response.data
            } catch (error) {
                this.error = error
                throw error
            } finally {
                this.loading = false
            }
        },

        async createTool(data: ToolCreate): Promise<Tool> {
            const response = await toolService.createTool(data)
            this.tools.push(response.data)
            return response.data
        },

        async updateTool(id: number, data: ToolUpdate): Promise<Tool> {
            const response = await toolService.updateTool(id, data)
            const index = this.tools.findIndex(t => t.id === id)
            if (index !== -1) this.tools[index] = response.data
            return response.data
        },

        async deleteTool(id: number): Promise<void> {
            await toolService.deleteTool(id)
            this.tools = this.tools.filter(t => t.id !== id)
        },
    },
})
