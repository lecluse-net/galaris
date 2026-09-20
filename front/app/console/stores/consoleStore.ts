import { defineStore } from 'pinia'
import { consoleService, type EmbeddedProvisionResult, type ExecutorStatus } from '../services/consoleService'

interface ConsoleState {
  availability: boolean | null
  availabilityLoading: boolean
  availabilityRequestId: number
  status: ExecutorStatus | null
  loading: boolean
  actionLoading: boolean
  error: string
  lastProvision: EmbeddedProvisionResult | null
}

export const useConsoleStore = defineStore('console-executor', {
  state: (): ConsoleState => ({
    availability: null,
    availabilityLoading: false,
    availabilityRequestId: 0,
    status: null,
    loading: false,
    actionLoading: false,
    error: '',
    lastProvision: null,
  }),
  actions: {
    async loadAvailability(force = false): Promise<void> {
      if (!force && (this.availabilityLoading || this.availability !== null)) return
      const requestId = ++this.availabilityRequestId
      this.availabilityLoading = true
      try {
        const { data } = await consoleService.availability()
        if (requestId === this.availabilityRequestId) this.availability = data.in_use
      } catch {
        if (requestId === this.availabilityRequestId) this.availability = false
      } finally {
        if (requestId === this.availabilityRequestId) this.availabilityLoading = false
      }
    },
    async refresh(): Promise<void> {
      this.loading = true
      this.error = ''
      try {
        const { data } = await consoleService.status()
        if (!data.ok) throw new Error(data.error || 'Executor unavailable')
        this.status = data.result
      } catch (error) {
        this.status = null
        this.error = error instanceof Error ? error.message : String(error)
      } finally {
        this.loading = false
      }
    },
    async action(operation: string, payload: Record<string, unknown> = {}): Promise<void> {
      this.actionLoading = true
      try {
        await consoleService.action(operation, payload)
        await this.refresh()
      } finally {
        this.actionLoading = false
      }
    },
    async provision(agentId: number): Promise<EmbeddedProvisionResult> {
      this.actionLoading = true
      try {
        const { data } = await consoleService.provision(agentId)
        this.lastProvision = data
        await this.loadAvailability(true)
        await this.refresh()
        return data
      } finally {
        this.actionLoading = false
      }
    },
  },
})
