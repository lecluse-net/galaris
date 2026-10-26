import { onBeforeUnmount, ref, shallowReactive, shallowRef } from 'vue'
import { isAxiosError } from 'axios'
import { documentService } from './services/documentService'
import type { DocumentLibraryEntry } from './types'
import { reconcileLibrarySnapshot } from '@/app/document/librarySnapshot'

/** Each open folder loads its complete direct contents, independently of list filters. */
export function useDocumentBranches(changed: (incoming?: DocumentLibraryEntry[]) => void) {
  const entries = shallowRef(shallowReactive<Record<string, DocumentLibraryEntry[]>>({}))
  const loading = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, boolean>>({})
  let generation = 0
  const requests = new Map<string, number>()
  const stale = new Set<string>()
  const controllers = new Map<string, AbortController>()
  async function load(id: string): Promise<void> {
    if (loading.value[id]) return
    if (entries.value[id] && !errors.value[id] && !stale.has(id)) return
    const current = generation
    const controller = new AbortController()
    controllers.set(id, controller)
    const request = (requests.get(id) ?? 0) + 1
    requests.set(id, request)
    const valid = () => generation === current && requests.get(id) === request
    loading.value[id] = true; errors.value[id] = false
    try {
      const documents: DocumentLibraryEntry[] = []
      let more = true
      while (more) {
        const parent = id === 'root' ? {} : id.startsWith('doc:') ? { parent_document_id: id.slice(4) } : { tag_id: id }
        const result = await documentService.browseDocumentLibrary({ ...parent, include_descendants: false,
          classification: id === 'root' ? 'root' : 'classified', sort_by: 'position', include_keywords: false,
          limit: 500, offset: documents.length }, controller.signal)
        if (!valid()) return
        documents.push(...result.entries)
        more = result.has_more && result.entries.length > 0
      }
      entries.value[id] = reconcileLibrarySnapshot(entries.value[id] ?? [], documents, entry => entry.item.id)
      stale.delete(id); changed(documents)
    } catch (error) {
      if (valid()) {
        errors.value[id] = true
        if (isAxiosError(error) && [401, 403, 404].includes(error.response?.status ?? 0)) {
          delete entries.value[id]; changed()
        }
      }
    }
    finally { if (valid()) { loading.value[id] = false; controllers.delete(id) } }
  }
  function close(id: string): void {
    controllers.get(id)?.abort(); controllers.delete(id)
    if (loading.value[id]) stale.add(id)
    requests.set(id, (requests.get(id) ?? 0) + 1)
    loading.value[id] = false
  }
  function reset(): void {
    for (const controller of controllers.values()) controller.abort()
    controllers.clear()
    ++generation; requests.clear(); stale.clear(); entries.value = shallowReactive<Record<string, DocumentLibraryEntry[]>>({}); loading.value = {}; errors.value = {}
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
