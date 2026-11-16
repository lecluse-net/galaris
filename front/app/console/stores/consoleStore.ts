import { toRaw } from 'vue'
import { withSessionScope, storeRequestFailure } from '@/core/util/facade'
import { sessionGeneration } from '@/core/api'
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

const statusReads = new WeakMap<object, symbol>()

export const useConsoleStore = withSessionScope(defineStore('console-executor', {
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
      const session = sessionGeneration()
      const current = () => session === sessionGeneration() && requestId === this.availabilityRequestId
      this.availabilityLoading = true
      try {
        const { data } = await consoleService.availability()
        if (current()) this.availability = data.in_use
      } catch {
        if (current()) this.availability = false
      } finally {
        if (current()) this.availabilityLoading = false
      }
    },
    async refresh(): Promise<void> {
      const reportFailure = storeRequestFailure(this, 'refresh')
      const request = Symbol(), session = sessionGeneration()
      statusReads.set(toRaw(this), request)
      const current = () => statusReads.get(toRaw(this)) === request && session === sessionGeneration()
      this.loading = true
      this.error = ''
      try {
        const { data } = await consoleService.status()
        if (!current()) return
        if (!data.ok) throw new Error(data.error || 'Executor unavailable')
        this.status = data.result
      } catch (error) {
        if (!current()) return
        this.status = null
        this.error = error instanceof Error ? error.message : String(error)
        reportFailure(error)
      } finally {
        if (current()) this.loading = false
      }
    },
    async action(operation: string, payload: Record<string, unknown> = {}): Promise<void> {
      const session = sessionGeneration()
      this.actionLoading = true
      try {
        await consoleService.action(operation, payload)
        if (session === sessionGeneration()) await this.refresh()
      } finally {
        if (session === sessionGeneration()) this.actionLoading = false
      }
    },
    async provision(agentId: number): Promise<EmbeddedProvisionResult> {
      const session = sessionGeneration()
      this.actionLoading = true
      try {
        const { data } = await consoleService.provision(agentId)
        if (session !== sessionGeneration()) return data
        this.lastProvision = data
        await this.loadAvailability(true)
        if (session === sessionGeneration()) await this.refresh()
        return data
      } finally {
        if (session === sessionGeneration()) this.actionLoading = false
      }
    },
  },
}), { flags: { refresh: 'loading', action: 'actionLoading', provision: 'actionLoading' } })
