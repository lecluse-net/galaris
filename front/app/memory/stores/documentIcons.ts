import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT } from '@/core/api'
import { memoryService } from '../services/memoryService'

export const useDocumentIcons = defineStore('memory.documentIcons', () => {
  const icons = ref<Record<string, string | null>>({})
  const errors = ref<Record<string, boolean>>({})
  const saving = ref<Record<string, boolean>>({})
  const session = ref(0)
  const pending = new Set<string>()
  const loading = new Set<string>()
  const versions = new Map<string, number>()
  let timer: ReturnType<typeof setTimeout> | undefined

  function ensure(id: string): void {
    if (id in icons.value || loading.has(id)) return
    pending.add(id); loading.add(id)
    timer ??= setTimeout(() => { timer = undefined; void flush() }, 0)
  }
  async function flush(): Promise<void> {
    const epoch = session.value
    const ids = [...pending]; pending.clear()
    for (let offset = 0; offset < ids.length; offset += 500) {
      const batch = ids.slice(offset, offset + 500)
      const requestedVersions = new Map(batch.map(id => [id, versions.get(id) ?? 0]))
      try {
        const result = await memoryService.resolveDocumentIcons(batch)
        if (session.value !== epoch) return
        for (const id of batch) if ((versions.get(id) ?? 0) === requestedVersions.get(id)) {
          icons.value[id] = result[id] ?? null; errors.value[id] = false
        }
      } catch {
        if (session.value !== epoch) return
        for (const id of batch) if ((versions.get(id) ?? 0) === requestedVersions.get(id)) errors.value[id] = true
      } finally { if (session.value === epoch) batch.forEach(id => loading.delete(id)) }
    }
  }
  async function save(id: string, icon: string | null): Promise<boolean> {
    if (saving.value[id]) return false
    const epoch = session.value
    saving.value[id] = true
    versions.set(id, (versions.get(id) ?? 0) + 1)
    try {
      const result = await memoryService.saveDocumentIcon(id, icon)
      if (session.value !== epoch) return false
      versions.set(id, (versions.get(id) ?? 0) + 1)
      icons.value[id] = result.icon; errors.value[id] = false
      return true
    } catch (error) { if (session.value === epoch) throw error; return false }
    finally { if (session.value === epoch) saving.value[id] = false }
  }
  function reset(): void {
    ++session.value
    clearTimeout(timer); timer = undefined
    pending.clear(); loading.clear(); versions.clear()
    icons.value = {}; errors.value = {}; saving.value = {}
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, reset)
  onScopeDispose(() => { reset(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, reset) })
  return { icons, errors, saving, session, ensure, save }
})
