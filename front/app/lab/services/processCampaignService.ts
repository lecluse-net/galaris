import { api } from '@/core/api'
export interface CampaignCase { id: string; status: string; position: number; run_id: string | null; evidence: Record<string, unknown> }
export interface ProcessCampaign { id: string; title: string; code: string; status: string; dataset_uri: string; total: number; page: number; page_size: number; items: CampaignCase[] }
export interface SyntheticCase { input: Record<string, unknown>; expected?: Record<string, unknown> | null }
const base = '/evaluation/process-campaigns'
export const processCampaignService = {
  async dataset(data: { agent_id: number; title: string; invocation_key: string; cases: SyntheticCase[] }): Promise<{ document_id: string; document_uri: string }> { return (await api.post(`${base}/datasets`, data)).data },
  async generate(data: { agent_id: number; code: string; title: string; instructions: string; count: number; invocation_key: string }): Promise<{ document_id: string; document_uri: string }> { return (await api.post(`${base}/datasets/generate`, data)).data },
  async start(data: { agent_id: number; code: string; title: string; dataset_document_id: string; invocation_key: string }): Promise<ProcessCampaign> { return (await api.post(base, data)).data },
  async get(id: string, page = 1, pageSize = 50): Promise<ProcessCampaign> { return (await api.get(`${base}/${id}`, { params: { page, page_size: pageSize } })).data },
  async cancel(id: string): Promise<ProcessCampaign> { return (await api.post(`${base}/${id}/cancel`)).data },
}
