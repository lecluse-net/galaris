import { toRaw } from 'vue'
import { withSessionScope } from '@/core/util/facade'
import { defineStore } from 'pinia'
import serviceApi, { type Service, type ServiceCreate, type ServiceUpdate } from '../services/serviceApi'
import { sessionGeneration } from '@/core/api'

interface ServiceState {
    services: Service[]
    loading: boolean
    error: unknown
}

const reads = new WeakMap<object, AbortController>()
function invalidateReads(store: object): void {
    reads.get(toRaw(store))?.abort()
    reads.delete(toRaw(store))
}

export const useServiceStore = withSessionScope(defineStore('service', {
    state: (): ServiceState => ({
        services: [],
        loading: false,
        error: null,
    }),

    actions: {
        async fetchServices(): Promise<void> {
            invalidateReads(this)
            const request = new AbortController(), session = sessionGeneration()
            reads.set(toRaw(this), request)
            const current = () => reads.get(toRaw(this)) === request && session === sessionGeneration()
            this.loading = true
            this.error = null
            try {
                const response = await serviceApi.getServices(request.signal)
                if (current()) this.services = response.data
            } catch (error) {
                if (!current()) return
                this.error = error
                throw error
            } finally {
                if (current()) { this.loading = false; reads.delete(toRaw(this)) }
            }
        },

        async createService(data: ServiceCreate): Promise<Service> {
            invalidateReads(this)
            const response = await serviceApi.createService(data)
            invalidateReads(this)
            this.services.push(response.data)
            return response.data
        },

        async updateService(id: number, data: ServiceUpdate): Promise<Service> {
            invalidateReads(this)
            const response = await serviceApi.updateService(id, data)
            invalidateReads(this)
            const index = this.services.findIndex(t => t.id === id)
            if (index !== -1) this.services[index] = response.data
            return response.data
        },

        async deleteService(id: number, confirmationVersion?: string): Promise<void> {
            invalidateReads(this)
            await serviceApi.deleteService(id, confirmationVersion)
            invalidateReads(this)
            this.services = this.services.filter(t => t.id !== id)
        },
    },
}), { flags: {"fetchServices":"loading"} })
