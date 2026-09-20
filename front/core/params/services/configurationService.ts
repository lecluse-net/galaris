import api from '@/core/api'
import type { AxiosResponse } from 'axios'

export interface MessengerConnectionCheck {
    connection_id: number
    agent_id: number
    provider: string
    ok: boolean
    identity: string
    detail: string
    receiving: boolean | null
    last_received_at: string | null
}

export interface MessengerConfigurationCheck {
    provider: string
    ok: boolean
    connections: MessengerConnectionCheck[]
}

export type MemoryLinkReconciliationTriggerMode =
    | 'manual_only'
    | 'after_dream'
    | 'scheduled'
    | 'after_dream_and_scheduled'

export type MemoryLinkReconciliationJobStatus =
    | 'pending'
    | 'running'
    | 'success'
    | 'error'

export interface MemoryLinkReconciliationStatus {
    trigger_mode: MemoryLinkReconciliationTriggerMode
    after_dream_enabled: boolean
    scheduled_enabled: boolean
    interval_hours: number
    idle_only: boolean
    latest_job_status: MemoryLinkReconciliationJobStatus | null
    latest_job_trigger: string | null
    latest_job_created_at: string | null
    last_completed_at: string | null
    next_scheduled_at: string | null
    job_pending: boolean
}

export interface MemoryLinkReconciliationRunResult {
    scope_item_id: string | null
    sources_scanned: number
    desired: number
    created: number
    updated: number
    removed: number
    unchanged: number
    manual_conflicts: number
    incomplete_sources: number
    contact_memberships_created: number
    contact_memberships_updated: number
    contact_memberships_removed: number
    topic_contact_memberships_created: number
    topic_contact_memberships_updated: number
    topic_contact_memberships_removed: number
    suggestions_available: boolean
}

export const configurationService = {
    testMessenger(): Promise<AxiosResponse<MessengerConfigurationCheck>> {
        return api.post('/messenger/configuration/test')
    },
    getMemoryLinkReconciliationStatus(): Promise<AxiosResponse<MemoryLinkReconciliationStatus>> {
        return api.get('/memory/link-reconciliation')
    },
    launchMemoryLinkReconciliation(): Promise<AxiosResponse<MemoryLinkReconciliationRunResult>> {
        return api.post('/memory/link-reconciliation')
    },
}
