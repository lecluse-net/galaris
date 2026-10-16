import { onBeforeUnmount, ref } from 'vue'
import { isAxiosError } from 'axios'
import { memoryService } from './services/memoryService'
import type { DocumentLibraryEntry } from './types'
import { reconcileLibrarySnapshot } from './librarySnapshot'

/** Each open folder loads its complete direct contents, independently of list filters. */
export function useDocumentBranches(changed: () => void) {
  const entries = ref<Record<string, DocumentLibraryEntry[]>>({})
  const loading = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, boolean>>({})
  let generation = 0
  const requests = new Map<string, number>()
  const stale = new Set<string>()
  async function load(id: string): Promise<void> {
    if (loading.value[id]) return
    if (entries.value[id] && !errors.value[id] && !stale.has(id)) return
    const current = generation
    const request = (requests.get(id) ?? 0) + 1
    requests.set(id, request)
    const valid = () => generation === current && requests.get(id) === request
    loading.value[id] = true; errors.value[id] = false
    try {
      const documents: DocumentLibraryEntry[] = []
      let more = true
      while (more) {
        const parent = id.startsWith('doc:') ? { parent_document_id: id.slice(4) } : { tag_id: id }
        const result = await memoryService.browseDocumentLibrary({ ...parent, include_descendants: false,
          classification: 'classified', sort_by: 'position', limit: 500, offset: documents.length })
        if (!valid()) return
        documents.push(...result.entries)
        more = result.has_more && result.entries.length > 0
      }
      entries.value[id] = reconcileLibrarySnapshot(entries.value[id] ?? [], documents, entry => entry.item.id)
      stale.delete(id); changed()
    } catch (error) {
      if (valid()) {
        errors.value[id] = true
        if (isAxiosError(error) && [401, 403, 404].includes(error.response?.status ?? 0)) {
          delete entries.value[id]; changed()
        }
      }
    }
    finally { if (valid()) loading.value[id] = false }
  }
  function close(id: string): void {
    if (loading.value[id]) stale.add(id)
    requests.set(id, (requests.get(id) ?? 0) + 1)
    loading.value[id] = false
  }
  function reset(): void {
    ++generation; requests.clear(); stale.clear(); entries.value = {}; loading.value = {}; errors.value = {}
  }
  function invalidate(ids = [...new Set([...Object.keys(entries.value), ...requests.keys()])]): void {
    // Supersede pending reads while retaining mounted rows until their replacements arrive.
    for (const id of ids) {
      close(id)
      stale.add(id)
    }
  }
  function forget(id: string): void {
    close(id)
    stale.delete(id)
    delete entries.value[id]; delete errors.value[id]
  }
  async function refresh(id: string): Promise<void> {
    close(id)
    stale.add(id)
    await load(id)
  }
  onBeforeUnmount(reset)
  return { entries, loading, errors, load, close, reset, invalidate, forget, refresh }
}
