import { defineStore } from 'pinia'
import serviceApi, { type Service, type ServiceCreate, type ServiceUpdate } from '../services/serviceApi'
import { useConnectionStore } from '@/app/connection'

interface ServiceState {
    services: Service[]
    loading: boolean
    error: unknown
}

export const useServiceStore = defineStore('service', {
    state: (): ServiceState => ({
        services: [],
        loading: false,
        error: null,
    }),

    actions: {
        async fetchServices(): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await serviceApi.getServices()
                this.services = response.data
            } catch (error) {
                this.error = error
                throw error
            } finally {
                this.loading = false
            }
        },

        async createService(data: ServiceCreate): Promise<Service> {
            const response = await serviceApi.createService(data)
            this.services.push(response.data)
            return response.data
        },

        async updateService(id: number, data: ServiceUpdate): Promise<Service> {
            const response = await serviceApi.updateService(id, data)
            const index = this.services.findIndex(t => t.id === id)
            if (index !== -1) this.services[index] = response.data
            return response.data
        },

        async deleteService(id: number, confirmationVersion?: string): Promise<void> {
            const connections = useConnectionStore()
            await serviceApi.deleteService(id, confirmationVersion)
            this.services = this.services.filter(t => t.id !== id)
            connections.forgetDeletedTool(id)
        },
    },
})
