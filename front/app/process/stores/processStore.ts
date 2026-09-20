import { defineStore } from 'pinia'
import {
  processService,
  type AgentOption,
  type ToolProcessDefinition,
  type ProcessAnalysis,
  type ProcessDefinition,
  type ProcessDefinitionCreate,
  type ProcessRun,
  type ProcessEngineHealth,
  type ProcessOperations,
} from '../services/processService'

interface ProcessState {
  runsRequest: number
  detailRequest: number
  definitionsRequest: number
  definitions: ProcessDefinition[]
  runs: ProcessRun[]
  runsTotal: number
  runsPage: number
  runsPageSize: number
  runsSearch: string
  runsSortBy: string
  runsDescending: boolean
  runsWorkflowId: string | null
  loadingRuns: boolean
  agents: AgentOption[]
  discovered: ToolProcessDefinition[]
  currentRun: ProcessRun | null
  currentAnalysis: ProcessAnalysis | null
  health: ProcessEngineHealth | null
  operations: ProcessOperations | null
  loading: boolean
  error: unknown
}

export const useProcessStore = defineStore('processes', {
  state: (): ProcessState => ({
    runsRequest: 0, detailRequest: 0, definitionsRequest: 0,
    definitions: [], runs: [], runsTotal: 0, runsPage: 1, runsPageSize: 50,
    runsSearch: '', runsSortBy: 'created_at', runsDescending: true,
    runsWorkflowId: null, loadingRuns: false,
    agents: [], discovered: [],
    currentRun: null, currentAnalysis: null, health: null, operations: null,
    loading: false, error: null,
  }),
  actions: {
    async loadAll(agentId?: number): Promise<void> {
      const request = ++this.definitionsRequest
      this.loading = true
      this.error = null
      try {
        const [definitions, agents] = await Promise.all([
          processService.definitions(agentId), processService.agents(),
        ])
        if (request !== this.definitionsRequest) return
        this.$patch({ definitions, agents })
      } catch (error) {
        if (request !== this.definitionsRequest) return
        this.error = error
        console.error('Error loading process administration:', error)
        throw error
      } finally { if (request === this.definitionsRequest) this.loading = false }
    },
    async saveDefinition(data: ProcessDefinitionCreate, agentId?: number): Promise<ProcessDefinition> {
      const record = await processService.createDefinition(data)
      await this.loadDefinitions(agentId)
      return record
    },
    async loadDefinitions(agentId?: number): Promise<void> {
      const request = ++this.definitionsRequest
      try {
        const definitions = await processService.definitions(agentId)
        if (request === this.definitionsRequest) this.definitions = definitions
      } finally { if (request === this.definitionsRequest) this.loading = false }
    },
    async deleteDefinition(id: number): Promise<void> {
      await processService.deleteDefinition(id)
      this.definitions = this.definitions.filter(item => item.id !== id)
    },
    async sync(toolCode: string): Promise<void> { this.discovered = await processService.syncDefinitions(toolCode) },
    async loadHealth(toolCode: string): Promise<void> { this.health = await processService.toolHealth(toolCode) },
    async loadOperations(): Promise<void> { this.operations = await processService.operations() },
    async loadRuns(
      workflowId?: string,
      page?: number,
      pageSize?: number,
      search?: string,
      sortBy?: string,
      descending?: boolean,
    ): Promise<void> {
      workflowId ??= this.runsWorkflowId ?? undefined
      page ??= this.runsPage
      pageSize ??= this.runsPageSize
      search ??= this.runsSearch
      sortBy ??= this.runsSortBy
      descending ??= this.runsDescending
      const request = ++this.runsRequest
      this.loadingRuns = true
      try {
        const result = await processService.runs({
          workflowId, page, pageSize, search, sortBy, descending,
        })
        if (request !== this.runsRequest) return
        this.$patch((state) => {
          state.runs = result.items
          state.runsTotal = result.total
          state.runsPage = result.page
          state.runsPageSize = result.page_size
          state.runsSearch = search
          state.runsSortBy = sortBy
          state.runsDescending = descending
          state.runsWorkflowId = workflowId ?? null
        })
      } finally {
        if (request === this.runsRequest) this.loadingRuns = false
      }
    },
    async startRun(data: { agent_id: number; workflow_id: string; input: Record<string, unknown>; files: never[]; wait_for_completion: boolean }): Promise<void> {
      await processService.startRun(data)
    },
    async openRun(id: string): Promise<void> {
      const request = ++this.detailRequest
      this.currentRun = null
      this.currentAnalysis = null
      try {
        const run = await processService.run(id)
        if (request === this.detailRequest) this.currentRun = run
      } catch (error) { if (request === this.detailRequest) throw error }
    },
    closeRun(): void {
      this.detailRequest += 1
      this.currentRun = null
      this.currentAnalysis = null
    },
    async deleteRun(id: string): Promise<void> {
      const request = this.detailRequest
      try { await processService.deleteRun(id) }
      catch (error) { if (request === this.detailRequest) throw error; return }
      this.$patch((state) => {
        if (request === state.detailRequest && state.currentRun?.id === id) {
          state.detailRequest += 1
          state.currentRun = null
          state.currentAnalysis = null
        }
      })
      const targetPage = this.runs.length === 1 && this.runsPage > 1
        ? this.runsPage - 1
        : this.runsPage
      await this.loadRuns(undefined, targetPage)
    },
    async refreshRun(id: string): Promise<void> {
      const request = this.detailRequest
      try {
        await processService.refreshRun(id)
      } catch (error) {
        if (request === this.detailRequest && this.currentRun?.id === id) throw error
      } finally {
        if (request === this.detailRequest && this.currentRun?.id === id) await this.openRun(id)
        await this.loadRuns()
      }
    },
    async cancelRun(id: string): Promise<void> {
      const request = this.detailRequest
      try { await processService.cancelRun(id) }
      catch (error) { if (request === this.detailRequest && this.currentRun?.id === id) throw error }
      if (request === this.detailRequest && this.currentRun?.id === id) await this.openRun(id)
      await this.loadRuns()
    },
    async retryRun(id: string): Promise<void> {
      await processService.retryRun(id)
      await this.loadRuns(undefined, 1)
    },
    async analyzeRun(id: string): Promise<void> {
      const request = this.detailRequest
      try {
        const analysis = await processService.analyzeRun(id)
        if (request === this.detailRequest && this.currentRun?.id === id) this.currentAnalysis = analysis
      } catch (error) { if (request === this.detailRequest && this.currentRun?.id === id) throw error }
    },
  },
})
