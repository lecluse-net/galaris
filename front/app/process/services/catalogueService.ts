import { api } from '@/core/api'
import type { ProcessRunStatus } from './processService'

export type CatalogueKind = 'all' | 'native' | 'external'
export type CatalogueArchive = 'all' | 'active' | 'archived'
export type CatalogueSort = 'label' | 'tool' | 'agent' | 'description'
export interface CatalogueItem {
  id: number; code: string | null; label: string; description: string | null; archived: boolean
  tool: string; agent: string | null; active_runs: number; human_waiting_runs: number
  latest_run: { id: string; status: ProcessRunStatus; created_at: string } | null
}
export interface CataloguePage { items: CatalogueItem[]; total: number; page: number; page_size: number }
export const catalogueService = {
  async list(params: { page: number; page_size: number; search: string; kind: CatalogueKind; archive: CatalogueArchive;
    agent_id: number | null; sort_by: CatalogueSort; descending: boolean }): Promise<CataloguePage> {
    return (await api.get<CataloguePage>('/processes/catalogue', { params })).data
  },
}
