import { api } from '@/core/api'
import type { SharingDraft } from '@/app/share'
import type { Dataset, Page, DatasetSharing, DatasetUsage, UsageKind } from '../types'
const base = '/datasets'
export const datasetService = {
  async list(page = 1, page_size = 50, q = ''): Promise<Page<Dataset>> { return (await api.get(base, { params: { page, page_size, q } })).data },
  async create(title: string, content = '[]'): Promise<Dataset> { return (await api.post(base, { title, content })).data },
  async read(id: string): Promise<Dataset> { return (await api.get(`${base}/${id}`)).data },
  async write(id: string, content: string, expected_revision: number, title?: string, expected_lock_version?: number): Promise<Dataset> { return (await api.put(`${base}/${id}/content`, { content, expected_revision, title, expected_lock_version })).data },
  async metadata(id: string, expected_lock_version: number, values: Record<string, unknown>): Promise<Dataset> { return (await api.patch(`${base}/${id}`, { expected_lock_version, ...values })).data },
  async history(id: string, page = 1, page_size = 50): Promise<Page<{ revision: number; created_at: string }>> { return (await api.get(`${base}/${id}/revisions`, { params: { page, page_size } })).data },
  async revision(id: string, revision: number): Promise<{ content: string }> { return (await api.get(`${base}/${id}/revisions/${revision}`)).data },
  async restore(id: string, number: number, expected_revision: number): Promise<Dataset> { return (await api.post(`${base}/${id}/revisions/${number}/restore`, { expected_revision })).data },
  async sharing(id: string): Promise<DatasetSharing> { return (await api.get(`${base}/${id}/sharing`)).data },
  async share(id: string, draft: SharingDraft, expected_lock_version: number): Promise<DatasetSharing> { return (await api.put(`${base}/${id}/sharing-level`, { ...draft, expected_lock_version })).data },
  async usages(id: string, kind: UsageKind, page = 1, page_size = 50): Promise<Page<DatasetUsage>> { return (await api.get(`${base}/${id}/usages`, { params: { kind, page, page_size } })).data },
  async remove(id: string, expected_lock_version: number): Promise<void> { await api.delete(`${base}/${id}`, { params: { expected_lock_version } }) },
}
