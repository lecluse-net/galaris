/** Public HTTP client and contracts for the Harness catalogue and assignments. */
import type { AxiosResponse } from 'axios'

import api from '@/core/api'

export type HarnessAction = 'start' | 'stop' | 'restart' | 'update'
export type HarnessCapability = HarnessAction | 'status' | 'logs' | 'refresh' | 'execute' | 'streaming' | 'skills' | 'runtime_files' | 'mcp' | 'memory'
    | 'cancellation' | 'local_interrupt' | 'remote_cancel_acknowledged' | 'checkpoints' | 'checkpoint_rebase'
    | 'resume' | 'effect_reconciliation' | 'semantic_events' | 'structured_tool_events' | 'normalized_usage'
    | 'taskless_runs' | 'approvals' | 'voice_calling' | 'file_tools' | 'console_execution'

export interface HarnessExecutionPolicy {
    disabled_capabilities: HarnessCapability[]
    max_parallel_tasks: number | null
    stream_close_timeout_seconds: number
    execution_timeout_seconds: number | null
    idle_timeout_seconds: number | null
    max_message_bytes: number
    max_result_bytes: number
    max_stream_bytes: number
}

export interface HarnessExecutionConfiguration {
    provider_code: string
    label: string
    revision: number
    pipeline_policy: {
        use_planner: boolean
        use_briefing: boolean
        briefing_efforts: string[]
    }
    descriptor: {
        schema_version: 'galaris.harness-capabilities/v1'
        implemented: HarnessCapability[]
        configurable: HarnessCapability[]
        configured: HarnessCapability[]
        verified: HarnessCapability[]
        effective: HarnessCapability[]
        unavailable: Record<string, string>
        policy: HarnessExecutionPolicy
        revision: number
    }
}

export interface HarnessRuntimeState {
    skills_status?: 'not_applicable' | 'pending' | 'current' | 'error'
    available_actions?: HarnessCapability[]
    status: string
    capabilities: HarnessCapability[]
    lifecycle_status: 'absent' | 'provisioning' | 'ready' | 'deprovisioning' | 'error' | 'internal'
    managed: boolean
    last_error: string | null
}

export interface HarnessSelection {
    id: string | null
    harness_id: string | null
    agent_id: number
    internal: boolean
    name: string
    provider_code: string
    driver_code: string
    base_url: string | null
    model: string | null
    token_configured: boolean
    lifecycle_status: 'absent' | 'provisioning' | 'ready' | 'deprovisioning' | 'error'
    revision: number
    capabilities: HarnessCapability[]
    containerized: boolean
    last_error: string | null
}

export interface HarnessCatalogEntry {
    id: string
    name: string
    provider_code: string
    provider_label: string
    driver_code: string
    enabled: boolean
    base_url: string | null
    model: string | null
    token_configured: boolean
    settings: Record<string, unknown>
    revision: number
    capabilities: HarnessCapability[]
    containerized: boolean
    assigned_agents: number
    last_error: string | null
}

export interface HarnessCatalogCreate {
    provider_code: 'openai_messages'
    name: string
    enabled: boolean
    base_url?: string | null
    token?: string | null
    model?: string | null
    settings?: Record<string, unknown>
}

export interface HarnessCatalogUpdate {
    name: string
    enabled: boolean
    base_url?: string | null
    token?: string | null
    model?: string | null
    settings?: Record<string, unknown>
}

export interface HarnessProbeResult {
    ok: boolean
    base_url: string
    models: string[]
}

export interface HarnessTaskBlocker {
    id: string
    label: string
}

export interface HarnessTaskBlockers {
    active_tasks: HarnessTaskBlocker[]
    paused_tasks: HarnessTaskBlocker[]
    active_count: number
}

export const harnessService = {
    executionConfigurations(): Promise<AxiosResponse<HarnessExecutionConfiguration[]>> {
        return api.get('/harnesses/execution-configurations')
    },
    saveExecutionConfiguration(code: string, expectedRevision: number, policy: HarnessExecutionPolicy): Promise<AxiosResponse<HarnessExecutionConfiguration>> {
        return api.put(`/harnesses/execution-configurations/${encodeURIComponent(code)}`, {
            expected_revision: expectedRevision, policy,
        })
    },
    catalog(enabledOnly = false): Promise<AxiosResponse<HarnessCatalogEntry[]>> {
        return api.get('/harnesses/catalog', { params: { enabled_only: enabledOnly } })
    },
    catalogEntry(harnessId: string): Promise<AxiosResponse<HarnessCatalogEntry>> {
        return api.get(`/harnesses/catalog/${harnessId}`)
    },
    createCatalogEntry(data: HarnessCatalogCreate): Promise<AxiosResponse<HarnessCatalogEntry>> {
        return api.post('/harnesses/catalog', data)
    },
    updateCatalogEntry(
        harnessId: string,
        data: HarnessCatalogUpdate,
    ): Promise<AxiosResponse<HarnessCatalogEntry>> {
        return api.put(`/harnesses/catalog/${harnessId}`, data)
    },
    deleteCatalogEntry(harnessId: string): Promise<AxiosResponse<void>> {
        return api.delete(`/harnesses/catalog/${harnessId}`)
    },
    probe(data: {
        harness_id?: string
        base_url: string
        token?: string | null
    }): Promise<AxiosResponse<HarnessProbeResult>> {
        return api.post('/harnesses/catalog/probe', data)
    },
    selection(agentId: number): Promise<AxiosResponse<HarnessSelection>> {
        return api.get(`/harnesses/agents/${agentId}`)
    },
    install(agentId: number, harnessId: string): Promise<AxiosResponse<HarnessSelection>> {
        return api.put(`/harnesses/agents/${agentId}`, { harness_id: harnessId }, { timeout: 1_260_000 })
    },
    selectInternal(agentId: number): Promise<AxiosResponse<HarnessSelection>> {
        return api.delete(`/harnesses/agents/${agentId}`, { timeout: 1_260_000 })
    },
    taskBlockers(agentId: number): Promise<AxiosResponse<HarnessTaskBlockers>> {
        return api.get(`/harnesses/agents/${agentId}/task-blockers`)
    },
    terminatePausedTasks(agentId: number): Promise<AxiosResponse<HarnessTaskBlockers>> {
        return api.post(`/harnesses/agents/${agentId}/task-blockers/terminate-paused`)
    },
    status(agentId: number): Promise<AxiosResponse<HarnessRuntimeState>> {
        return api.get(`/harnesses/agents/${agentId}/status`)
    },
    action(
        agentId: number,
        action: HarnessAction,
    ): Promise<AxiosResponse<{ status: string; output: string }>> {
        return api.post(`/harnesses/agents/${agentId}/actions/${action}`, undefined, { timeout: 1_260_000 })
    },
    logs(agentId: number, lines = 300): Promise<AxiosResponse<{ lines: string[] }>> {
        return api.get(`/harnesses/agents/${agentId}/logs`, { params: { lines } })
    },
}
