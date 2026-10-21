import { api } from '@/core/api'
import type { SharingDraft } from '@/app/share'
import { createOwnerOptionsCache } from '@/app/share'
import type { Dataset, DatasetFolder, DatasetMove, DatasetOwnerOptions, Page, DatasetSharing, DatasetUsage, UsageKind } from '../types'
import type { Collaborator } from '@/app/share'
const base = '/datasets'
const ownerOptionsCache = createOwnerOptionsCache<DatasetOwnerOptions>()
export const datasetService = {
  async list(page = 1, page_size = 50, q = '', owner_agent_id?: number | null, filters: Record<string, unknown> = {}): Promise<Page<Dataset>> { return (await api.get(base, { params: { page, page_size, q, owner_agent_id, ...filters } })).data },
  async folders(): Promise<DatasetFolder[]> { return (await api.get(`${base}/tags`)).data },
  async createFolder(name: string, parent_id: string | null): Promise<DatasetFolder> { return (await api.post(`${base}/tags`, { name, parent_id })).data },
  async saveFolder(folder: DatasetFolder): Promise<void> { await api.put(`${base}/tags/${folder.id}`, { name: folder.name, parent_id: folder.parent_id, icon: folder.icon }) },
  async removeFolder(id: string, confirmed = false): Promise<{ deleted: boolean }> { return (await api.delete(`${base}/tags/${id}`, { params: { confirmed } })).data },
  async sortFolder(id: string, descending: boolean): Promise<void> { await api.post(`${base}/tags/${id}/sort`, null, { params: { descending } }) },
  async move(move: DatasetMove): Promise<void> { await api.post(`${base}/library/move`, move) },
  async facets(): Promise<{ owners: Collaborator[]; keywords: string[]; current_user_id: number }> { return (await api.get(`${base}/library/facets`)).data },
  async create(title: string, content = '[]'): Promise<Dataset> { return (await api.post(base, { title, content })).data },
  async read(id: string): Promise<Dataset> { return (await api.get(`${base}/${id}`)).data },
  async owner(id: string, lockVersion?: number): Promise<DatasetOwnerOptions> {
    const load = async (signal?: AbortSignal): Promise<DatasetOwnerOptions> => (await api.get<DatasetOwnerOptions>(`${base}/${id}/owner`, { signal })).data
    return lockVersion === undefined ? load() : ownerOptionsCache.read(`${id}:${lockVersion}`, load)
  },
  async transferOwner(id: string, kind: 'agent' | 'user', principal: number, expected_lock_version: number): Promise<Dataset> { return (await api.patch(`${base}/${id}/owner`, { kind, principal, expected_lock_version })).data },
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
