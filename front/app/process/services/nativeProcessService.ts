import { api } from '@/core/api'
import type { SharingState as DocumentSharing, SharingUpdate as DocumentSharingLevelUpdate } from '@/app/share'
import type { OwnerOption } from '@/app/share'
import { createOwnerOptionsCache } from '@/app/share/facade'

export type NodeKind = 'start' | 'end' | 'task' | 'human_task' | 'tool_call' | 'rest' | 'code' | 'program' | 'call' | 'if' | 'parallel' | 'for' | 'while'
export const valueTypes = ['int', 'float', 'string', 'bool', 'Agent', 'File', 'User', 'Document', 'array', 'object'] as const
export type ValueType = typeof valueTypes[number]
export type { JsonValue, TypedValue } from '@/app/dataset'
import type { TypedValue } from '@/app/dataset'
export interface ProcessVariable { name: string; type: ValueType; nullable: boolean; default?: TypedValue }
export interface ProcessActor { id: string; name: string; kind: 'agent' | 'human'; agent_id: number | null; user_id: number | null }
export interface ProcessAgentOption { id: number; label: string; has_avatar?: boolean }
export interface ProcessDecisionModel { id: number; label: string; provider: string; decision: boolean }
export interface BpmnNode {
  id: string; kind: NodeKind; title: string; config: Record<string, unknown>; x: number; y: number; body: BpmnGraph | null
  inputs?: ProcessVariable[]; outputs?: ProcessVariable[]
}
export interface BpmnFlow { id: string; source: string; target: string; condition: string | null }
export interface BpmnGraph {
  schema_version: 'galaris.bpmn/v1' | 'galaris.bpmn/v2'; nodes: BpmnNode[]; flows: BpmnFlow[]
  inputs?: ProcessVariable[]; outputs?: ProcessVariable[]
  actors?: ProcessActor[]
  execution_agent_id?: number | null
}
export interface NativeDefinition {
  id: number; code: string; title: string; description: string | null; revision: number; archived: boolean; can_write: boolean
  graph: BpmnGraph; xml: string; diagnostics: { node: string; code: string; severity: string; message: string }[]
  owner: OwnerOption | null; can_manage: boolean; lock_version: number
}
export type NativeDefinitionSummary = Pick<NativeDefinition, 'id' | 'code' | 'title' | 'archived'>
export interface DefinitionPage { items: NativeDefinitionSummary[]; total: number; page: number; page_size: number }
export interface NodeOccurrence {
  id: string; node_key: string; status: string; started_at: string | null; finished_at: string | null
  output: Record<string, unknown> | null; body_path: string[]; iteration: number | null
}
export interface NodeAttempt {
  id: string; number: number; status: string; input: Record<string, unknown> | null; prompt: string | null
  receipt: Record<string, unknown> | null; task_uri: string | null; child_run_id: string | null; error: string | null
}
export interface NodeExecutionDetail extends NodeOccurrence { attempts: NodeAttempt[] }
export interface NodeOccurrencePage { items: NodeOccurrence[]; total: number; page: number; page_size: number }
export interface RunActivity {
  kind: string; occurrence_id: string; node_key: string; title?: string; body_path: string[]; since: string | null
  question?: string; run_id?: string
  task?: { last_error: string | null; pause_reasons: string[]; waits: { kind: string; question?: string }[] }
}
export interface RunObservation {
  phase: string; last_activity_at: string; activities: RunActivity[]; activities_truncated: boolean
  progress: { occurrences: number; completed: number; failed: number; ready: number; active: number; cancelled: number }
  blocker: { code: string; requires_reconciliation: boolean } | null
  available_actions: ('pause' | 'resume' | 'step' | 'cancel')[]
}
export interface NativeRun {
  label?: string
  id: string; status: string; graph: BpmnGraph | null; definition_revision: number
  operational?: RunObservation
  can_control: boolean; node_statuses: Record<string, string>; debugger_revision: number
  data: Record<string, unknown>; data_revision: number; data_uri: string; attachments_uri: string
  files: { uri: string; filename?: string; description?: string; content_type?: string; size?: number }[]
  paused: boolean; breakpoints: string[]; output: Record<string, unknown> | null
  error: string | null; error_code: string | null; parent_run_id: string | null; nodes: NodeOccurrence[]; total: number; page: number; page_size: number
  event_cursor: number; events: { id: number; type: string; payload: Record<string, unknown> }[]; duration_seconds: number | null
}
export interface Accounting { calls: number; cost: number | null; inference_cost: number | null; tokens: number | null; estimated_calls: number; duration_seconds?: number | null }
export interface NativeMetrics { direct: Accounting; inclusive: Accounting; tasks: Record<string, Accounting>; nodes: Record<string, Accounting>; partial: boolean
  occurrences?: Record<string, { node_key: string; direct: Accounting; inclusive: Accounting; duration_seconds: number | null }> }
export interface NativeRunSummary { id: string; status: string; process_label: string; engine_code: string; result_preview?: string; started_at?: string | null; finished_at?: string | null }
export interface NativeChildren { items: NativeRunSummary[]; total: number; page: number; page_size: number }
export interface ProcessHistory { items: { revision: number; created_at: string; author_agent_id: number | null }[]; total: number; has_more: boolean }

export const emptyGraph = (): BpmnGraph => ({ schema_version: 'galaris.bpmn/v2', inputs: [], outputs: [],
  actors: [], execution_agent_id: null,
  nodes: ['start', 'end'].map(id => ({ id, kind: id as 'start' | 'end', title: '', config: {}, x: 0, y: 0, body: null })),
  flows: [{ id: 'start_end', source: 'start', target: 'end', condition: null }] })

const base = '/processes/internal'
const ownerOptionsCache = createOwnerOptionsCache<OwnerOption[]>()
export const nativeProcessService = {
  async decisionModels(signal: AbortSignal): Promise<ProcessDecisionModel[]> {
    return (await api.get(`${base}/decision-models`, { signal })).data
  },
  runUrl(id: string): string { return `galaris://processes/runs/${encodeURIComponent(id)}` },
  async agents(): Promise<ProcessAgentOption[]> { return (await api.get(`${base}/agents`)).data },
  async ownerOptions(): Promise<OwnerOption[]> { return ownerOptionsCache.read('all', async signal => (await api.get<OwnerOption[]>(`${base}/owner-options`, { signal })).data) },
  async transferOwner(code: string, owner: OwnerOption, lockVersion: number): Promise<NativeDefinition> {
    return (await api.patch(`${base}/definitions/${encodeURIComponent(code)}/owner`, { kind: owner.kind, id: owner.id, expected_lock_version: lockVersion })).data
  },
  async sharingOptions(agentId: number, owner: 'user' | 'agent', ownerId?: number): Promise<DocumentSharing> {
    return (await api.get(`${base}/sharing-options`, { params: { agent_id: agentId, owner, owner_id: ownerId } })).data
  },
  async humans(agentId: number, signal?: AbortSignal): Promise<{ id: number; label: string }[]> {
    return (await api.get(`${base}/humans`, { params: { agent_id: agentId }, signal })).data
  },
  async list(page = 1, pageSize = 50): Promise<DefinitionPage> {
    return (await api.get(`${base}/definitions`, { params: { page, page_size: pageSize } })).data
  },
  async get(code: string): Promise<NativeDefinition> { return (await api.get(`${base}/definitions/${encodeURIComponent(code)}`)).data },
  async create(data: { title: string; description?: string; agent_id: number; owner: 'user' | 'agent'; owner_id?: number; graph?: BpmnGraph; xml?: string }): Promise<NativeDefinition> {
    return (await api.post(`${base}/definitions`, data)).data
  },
  async save(code: string, data: { title: string; description?: string; expected_revision: number; graph?: BpmnGraph; xml?: string }): Promise<NativeDefinition> {
    return (await api.put(`${base}/definitions/${encodeURIComponent(code)}`, data)).data
  },
  async validate(data: { graph?: BpmnGraph; xml?: string }): Promise<{ graph: BpmnGraph; xml: string }> {
    return (await api.post(`${base}/validate`, data)).data
  },
  async history(code: string, page = 1, pageSize = 50): Promise<ProcessHistory> {
    return (await api.get(`${base}/definitions/${encodeURIComponent(code)}/history`, { params: { page, page_size: pageSize, exclude_current: true } })).data
  },
  async revision(code: string, revision: number): Promise<{ detail: { content: string }; diff: { additions: number; deletions: number } }> {
    return (await api.get(`${base}/definitions/${encodeURIComponent(code)}/history/${revision}`)).data
  },
  async restore(code: string, revision: number, expectedRevision: number): Promise<NativeDefinition> {
    return (await api.post(`${base}/definitions/${encodeURIComponent(code)}/restore`, { revision, expected_revision: expectedRevision })).data
  },
  async deleteRevision(code: string, revision: number): Promise<void> {
    await api.delete(`${base}/definitions/${encodeURIComponent(code)}/history/${revision}`)
  },
  async archive(code: string, archived: boolean): Promise<NativeDefinition> {
    return (await api.post(`${base}/definitions/${encodeURIComponent(code)}/archive`, null, { params: { archived } })).data
  },
  async sharing(code: string): Promise<DocumentSharing> { return (await api.get(`${base}/definitions/${encodeURIComponent(code)}/sharing`)).data },
  async share(code: string, data: DocumentSharingLevelUpdate): Promise<DocumentSharing> { return (await api.put(`${base}/definitions/${encodeURIComponent(code)}/sharing`, data)).data },
  async run(id: string, page = 1, pageSize = 50, afterEvent = 0, agentId?: number | null): Promise<NativeRun> {
    return (await api.get(`${base}/runs/${id}`, { params: { page, page_size: pageSize, after_event: afterEvent, agent_id: agentId ?? undefined } })).data
  },
  async renameFile(id: string, fileId: string, name: string, agentId?: number | null): Promise<void> {
    await api.patch(`${base}/runs/${id}/files/${fileId}`, { name }, { params: { agent_id: agentId } })
  },
  async file(id: string, fileId: string, agentId?: number | null): Promise<Blob> {
    return (await api.get<Blob>(`${base}/runs/${id}/files/${fileId}`, { responseType: 'blob', params: { agent_id: agentId ?? undefined } })).data
  },
  async runs(code?: string, page = 1, pageSize = 50): Promise<NativeChildren> {
    return (await api.get(`${base}/runs`, { params: { code, page, page_size: pageSize } })).data
  },
  async metrics(id: string, agentId?: number | null): Promise<NativeMetrics> { return (await api.get(`${base}/runs/${id}/metrics`, { params: { agent_id: agentId ?? undefined } })).data },
  async node(id: string, nodeId: string, agentId?: number | null): Promise<NodeExecutionDetail> { return (await api.get(`${base}/runs/${id}/nodes/${nodeId}`, { params: { agent_id: agentId ?? undefined } })).data },
  async activityOccurrences(id: string, nodeKey: string, bodyPath: string[], page = 1, pageSize = 50, agentId?: number | null): Promise<NodeOccurrencePage> {
    return (await api.get(`${base}/runs/${id}/activities/${encodeURIComponent(nodeKey)}`, {
      params: { page, page_size: pageSize, agent_id: agentId ?? undefined, ...(bodyPath.length ? { body_path: bodyPath } : {}) },
      paramsSerializer: { indexes: null },
    })).data
  },
  async children(id: string, page = 1, pageSize = 50, agentId?: number | null): Promise<NativeChildren> {
    return (await api.get(`${base}/runs/${id}/children`, { params: { page, page_size: pageSize, agent_id: agentId ?? undefined } })).data
  },
  async control(id: string, action: 'pause' | 'resume' | 'step' | 'breakpoints', nodes: string[] = [], commandKey?: string, expectedRevision?: number): Promise<void> {
    await api.post(`${base}/runs/${id}/control`, { action, nodes, command_key: commandKey ?? crypto.randomUUID(), expected_revision: expectedRevision })
  },
  async cancel(id: string): Promise<void> { await api.post(`${base}/runs/${id}/cancel`) },
}
