import type { AxiosResponse } from 'axios'

import api from '@/core/api'

export interface HermesAgent {
    id: number
    code: string
    first_name: string
    last_name: string
    hermes_dashboard_enabled: boolean
    hermes_dashboard_port: number | null
    hermes_dashboard_username: string | null
    hermes_dashboard_password_configured: boolean
    hermes_config: string | null
    hermes_compose: string | null
    hermes_data_env: Record<string, string>
}

export interface HermesConfigUpdate {
    hermes_dashboard_enabled: boolean
    hermes_dashboard_port: number | null
    hermes_dashboard_username: string | null
    hermes_dashboard_password: string | null
    hermes_config: string | null
    hermes_compose: string | null
    hermes_data_env: Record<string, string>
}

export const hermesService = {
    listAgents(): Promise<AxiosResponse<HermesAgent[]>> {
        return api.get('/hermes/configurations')
    },
    updateConfig(id: number, config: HermesConfigUpdate): Promise<AxiosResponse<HermesAgent>> {
        return api.put(`/hermes/configurations/${id}`, config)
    },
}

export default hermesService
