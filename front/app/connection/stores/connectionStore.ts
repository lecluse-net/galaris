import { defineStore } from 'pinia'
import connectionService, {
    type ConnectionCreate,
    type ConnectionUpdate,
    type ConnectionParamCreate,
    type ConnectionParamUpdate,
    type ConnectionParamsResponse,
    type RefreshToolCatalogsResponse
} from '../services/connectionService'
import type { Connection, ConnectionParam } from '../services/connectionService'

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
            this.loading = true
            this.error = null
            try {
                const response = await connectionService.getConnectionParams(connectionId, decrypt)
                const params = response.data.params
                this.paramsCache[connectionId] = params
                this.configuredParamsCache[connectionId] = response.data.configured_params
                if (this.currentConnection?.id === connectionId) {
                    this.currentConnectionParams = params
                }
                return params
            } catch (error) {
                this.error = error
                console.error('Error fetching connection params:', error)
                throw error
            } finally {
                this.loading = false
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
