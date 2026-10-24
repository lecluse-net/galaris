import { defineStore } from 'pinia'
import { isAxiosError } from 'axios'
import { sessionGeneration } from '@/core/api'
import connectionService, {
    type ConnectionCreate,
    type ConnectionUpdate,
    type ConnectionParamCreate,
    type ConnectionParamUpdate,
    type ConnectionParamsResponse,
    type ConnectionOverview,
    type RefreshToolCatalogsResponse
} from '../services/connectionService'
import type { Connection, ConnectionParam } from '../services/connectionService'
import { CONNECTIONS_CHANGED_EVENT } from '../events'

export type { Connection, ConnectionParam, ConnectionParamsResponse }

interface ConnectionParamsCache {
    [connectionId: number]: Record<string, unknown>
}

interface ConnectionState {
    connections: Connection[]
    currentConnection: Connection | null
    currentConnectionParams: Record<string, unknown> | null
    paramsCache: ConnectionParamsCache
    configuredParamsCache: Record<number, string[]>
    loading: boolean
    error: unknown
}

const overviewReads = new WeakMap<object, symbol>()
const parameterReads = new WeakMap<object, Map<number, symbol>>()

function invalidateReads(store: object, connectionId?: number): void {
    overviewReads.delete(store)
    if (connectionId !== undefined) parameterReads.get(store)?.delete(connectionId)
}

export const useConnectionStore = defineStore('connection', {
    state: (): ConnectionState => ({
        connections: [],
        currentConnection: null,
        currentConnectionParams: null,
        paramsCache: {},
        configuredParamsCache: {},
        loading: false,
        error: null
    }),
    actions: {
        async fetchConnectionOverview(): Promise<void> {
            const request = Symbol('overview')
            const generation = sessionGeneration()
            overviewReads.set(this, request)
            const current = () => overviewReads.get(this) === request && generation === sessionGeneration()
            this.loading = true
            this.error = null
            try {
                const rows: ConnectionOverview[] = []
                const pageSize = 500
                for (let skip = 0; ; skip += pageSize) {
                    const { data } = await connectionService.getConnectionOverviews(skip, pageSize)
                    if (!current()) return
                    rows.push(...data)
                    if (data.length < pageSize) break
                }
                // Publish the rows and their parameters together, including removals.
                this.$patch(state => {
                    state.connections = rows.map(({ id, tool_id, agent_id, active }) => ({ id, tool_id, agent_id, active }))
                    state.paramsCache = Object.fromEntries(rows.map(row => [row.id, row.params]))
                    state.configuredParamsCache = Object.fromEntries(rows.map(row => [row.id, row.configured_params]))
                })
            } catch (error) {
                if (!current()) return
                if (isAxiosError(error) && [401, 403].includes(error.response?.status ?? 0)) {
                    this.connections = []
                    this.paramsCache = {}
                    this.configuredParamsCache = {}
                }
                this.error = error
                throw error
            } finally {
                if (current()) this.loading = false
            }
        },

        forgetDeletedTool(toolId: number): void {
            invalidateReads(this)
            this.loading = false
            this.connections = this.connections.filter(connection => connection.tool_id !== toolId)
            if (this.currentConnection?.tool_id === toolId) {
                this.currentConnection = null
                this.currentConnectionParams = null
            }
            this.paramsCache = {}
            this.configuredParamsCache = {}
            window.dispatchEvent(new Event(CONNECTIONS_CHANGED_EVENT))
        },
        // =====================================================================
        // Actions for Connection (parent table).
        // =====================================================================

        async fetchConnections(
            toolId?: number,
            agentId?: number,
            activeOnly?: boolean
        ): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.getConnections(toolId, agentId, activeOnly)
                this.connections = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching connections:', error)
            } finally {
                this.loading = false
            }
        },

        async fetchConnection(id: number): Promise<void> {
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.getConnection(id)
                this.currentConnection = response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching connection:', error)
            } finally {
                this.loading = false
            }
        },

        async createConnection(connection: ConnectionCreate): Promise<Connection> {
            invalidateReads(this)
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.createConnection(connection)
                this.connections.push(response.data)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating connection:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async updateConnection(id: number, connection: ConnectionUpdate): Promise<Connection> {
            invalidateReads(this, id)
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.updateConnection(id, connection)
                const index = this.connections.findIndex(c => c.id === id)
                if (index !== -1) {
                    this.connections[index] = response.data
                }
                if (this.currentConnection?.id === id) {
                    this.currentConnection = response.data
                }
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating connection:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async deleteConnection(id: number): Promise<void> {
            invalidateReads(this, id)
            this.loading = true
            this.error = null
            try {
                await connectionService.deleteConnection(id)
                this.connections = this.connections.filter(c => c.id !== id)
                // Clear the parameter cache.
                delete this.paramsCache[id]
                delete this.configuredParamsCache[id]
            } catch (error) {
                this.error = error
                console.error('Error deleting connection:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // Synchronize internal connections and force-refresh all live MCP catalogs.
        async refreshToolCatalogs(): Promise<RefreshToolCatalogsResponse> {
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.refreshToolCatalogs()
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error refreshing tool catalogs:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // =====================================================================
        // Actions for ConnectionParam (EAV table).
        // =====================================================================

        async fetchConnectionParams(connectionId: number, decrypt: boolean = false): Promise<Record<string, unknown>> {
            const reads = parameterReads.get(this) ?? new Map<number, symbol>()
            parameterReads.set(this, reads)
            const request = Symbol('params')
            const generation = sessionGeneration()
            reads.set(connectionId, request)
            const current = () => reads.get(connectionId) === request && generation === sessionGeneration()
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.getConnectionParams(connectionId, decrypt)
                const params = response.data.params
                if (!current()) return this.paramsCache[connectionId] ?? {}
                this.paramsCache[connectionId] = params
                this.configuredParamsCache[connectionId] = response.data.configured_params
                if (this.currentConnection?.id === connectionId) {
                    this.currentConnectionParams = params
                }
                return params
            } catch (error) {
                if (!current()) return this.paramsCache[connectionId] ?? {}
                this.error = error
                console.error('Error fetching connection params:', error)
                throw error
            } finally {
                if (current()) this.loading = false
            }
        },

        async getSingleParam(connectionId: number, paramName: string): Promise<ConnectionParam> {
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.getSingleParam(connectionId, paramName)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error fetching single param:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async createOrUpdateParam(param: ConnectionParamCreate): Promise<ConnectionParam> {
            invalidateReads(this, param.connection_id)
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.createOrUpdateParam(param)
                // Refresh the parameter cache for this connection.
                await this.fetchConnectionParams(param.connection_id)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating/updating param:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async createOrUpdateParamsBulk(
            connectionId: number,
            params: Record<string, string | null>
        ): Promise<ConnectionParam[]> {
            invalidateReads(this, connectionId)
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.createOrUpdateParamsBulk(connectionId, params)
                // Refresh the parameter cache.
                await this.fetchConnectionParams(connectionId)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error creating/updating params bulk:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async updateParam(
            connectionId: number,
            paramName: string,
            update: ConnectionParamUpdate
        ): Promise<ConnectionParam> {
            invalidateReads(this, connectionId)
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.updateParam(connectionId, paramName, update)
                // Refresh the cache.
                await this.fetchConnectionParams(connectionId)
                return response.data
            } catch (error) {
                this.error = error
                console.error('Error updating param:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        async deleteParam(connectionId: number, paramName: string): Promise<void> {
            invalidateReads(this, connectionId)
            this.loading = true
            this.error = null
            try {
                await connectionService.deleteParam(connectionId, paramName)
                // Refresh the cache.
                await this.fetchConnectionParams(connectionId)
            } catch (error) {
                this.error = error
                console.error('Error deleting param:', error)
                throw error
            } finally {
                this.loading = false
            }
        },

        // =====================================================================
        // Utilities
        // =====================================================================

        getParamsForConnection(connectionId: number): Record<string, unknown> | null {
            return this.paramsCache[connectionId] || null
        },

        getConfiguredParamsForConnection(connectionId: number): string[] {
            return this.configuredParamsCache[connectionId] || []
        },

        clearCurrentConnection(): void {
            this.currentConnection = null
            this.currentConnectionParams = null
        }
    }
})
