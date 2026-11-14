import { onBeforeUnmount, ref, shallowReactive, shallowRef } from 'vue'
import { isAxiosError } from 'axios'
import { documentService } from './services/documentService'
import type { DocumentLibraryEntry, DocumentLibraryRange } from './types'
import { reconcileLibrarySnapshot } from '@/app/document/librarySnapshot'
import { TREE_PAGE_SIZE, treePageFromKey, treePageDataKey } from '@/core/util'

/** Opening a directory or virtual range reads only its own 100 entries. */
export function useDocumentBranches(changed: (incoming?: DocumentLibraryEntry[]) => void) {
  const entries = shallowRef(shallowReactive<Record<string, DocumentLibraryEntry[]>>({}))
  const loading = ref<Record<string, boolean>>({})
  const errors = ref<Record<string, boolean>>({})
  const totals = ref<Record<string, number>>({})
  const ranges = ref<Record<string, DocumentLibraryRange[]>>({})
  let generation = 0
  const requests = new Map<string, number>()
  const stale = new Set<string>()
  const controllers = new Map<string, AbortController>()
  async function load(id: string): Promise<void> {
    const page = treePageFromKey(id)
    const parentId = page?.parent ?? id
    if (parentId.startsWith('local-tree:')) return
    id = treePageDataKey(id)
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
      const parent = parentId === 'root' ? {} : parentId.startsWith('doc:') ? { parent_document_id: parentId.slice(4) } : { tag_id: parentId }
      const result = await documentService.browseDocumentLibrary({ ...parent, include_descendants: false,
        classification: parentId === 'root' ? 'root' : 'classified', sort_by: 'position', include_keywords: false,
        limit: TREE_PAGE_SIZE, offset: page?.offset ?? 0,
        include_tree_ranges: !page || page.offset === 0 || page.size > TREE_PAGE_SIZE,
        tree_range_size: page && page.size > TREE_PAGE_SIZE ? page.size : undefined }, controller.signal)
      if (!valid()) return
      entries.value[id] = reconcileLibrarySnapshot(entries.value[id] ?? [], result.entries, entry => entry.item.id)
      totals.value[parentId] = result.total
      ranges.value[id] = result.tree_ranges ?? []
      stale.delete(id); changed(result.entries)
    } catch (error) {
      if (valid()) {
        errors.value[id] = true
        if (isAxiosError(error) && [401, 403, 404].includes(error.response?.status ?? 0)) {
          delete entries.value[id]; delete ranges.value[id]; changed()
        }
      }
    }
    finally { if (valid()) { loading.value[id] = false; controllers.delete(id) } }
  }
  function close(id: string): void {
    id = treePageDataKey(id)
    if (!treePageFromKey(id)) {
      for (const key of controllers.keys()) if (treePageFromKey(key)?.parent === id) close(key)
    }
    controllers.get(id)?.abort(); controllers.delete(id)
    if (loading.value[id]) stale.add(id)
    requests.set(id, (requests.get(id) ?? 0) + 1)
    loading.value[id] = false
  }
  function reset(): void {
    for (const controller of controllers.values()) controller.abort()
    controllers.clear()
    ++generation; requests.clear(); stale.clear(); entries.value = shallowReactive<Record<string, DocumentLibraryEntry[]>>({}); loading.value = {}; errors.value = {}; totals.value = {}
    ranges.value = {}
  }
  function cancelHidden(visible: Set<string>): void {
    for (const id of controllers.keys()) if (!visible.has(id)) close(id)
  }
  function invalidate(ids = [...new Set([...Object.keys(entries.value), ...requests.keys()])]): void {
    // Supersede pending reads while retaining mounted rows until their replacements arrive.
    const affected = new Set(ids)
    for (const key of Object.keys(entries.value)) if (affected.has(treePageFromKey(key)?.parent ?? key)) affected.add(key)
    for (const id of affected) {
      close(id)
      stale.add(id)
    }
  }
  function forget(id: string): void {
    close(id)
    stale.delete(id)
    delete entries.value[id]; delete errors.value[id]
    delete totals.value[id]
    delete ranges.value[id]
    for (const key of Object.keys(entries.value)) if (treePageFromKey(key)?.parent === id) forget(key)
  }
  async function refresh(id: string): Promise<void> {
    close(id)
    stale.add(id)
    await load(id)
  }
  onBeforeUnmount(reset)
  return { entries, loading, errors, totals, ranges, load, close, reset, invalidate, forget, refresh, cancelHidden }
}
