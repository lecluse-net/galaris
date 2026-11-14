import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { documentService } from '../services/documentService'

export const useDocumentIcons = defineStore('document.Icons', () => {
  const icons = ref<Record<string, string | null>>({})
  const errors = ref<Record<string, boolean>>({})
  const saving = ref<Record<string, boolean>>({})
  const session = ref(0)
  const pending = new Set<string>()
  const loading = new Set<string>()
  const versions = new Map<string, number>()
  const controllers = new Set<AbortController>()
  let authSession = sessionGeneration()
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
      const controller = new AbortController()
      controllers.add(controller)
      try {
        const result = await documentService.resolveDocumentIcons(batch, controller.signal)
        if (session.value !== epoch) return
        for (const id of batch) if ((versions.get(id) ?? 0) === requestedVersions.get(id)) {
          icons.value[id] = result[id] ?? null; errors.value[id] = false
        }
      } catch {
        if (session.value !== epoch) return
        for (const id of batch) if ((versions.get(id) ?? 0) === requestedVersions.get(id)) errors.value[id] = true
      } finally {
        controllers.delete(controller)
        if (session.value === epoch) batch.forEach(id => loading.delete(id))
      }
    }
  }
  async function save(id: string, icon: string | null): Promise<boolean> {
    if (saving.value[id]) return false
    const epoch = session.value
    saving.value[id] = true
    versions.set(id, (versions.get(id) ?? 0) + 1)
    try {
      const result = await documentService.saveDocumentIcon(id, icon)
      if (session.value !== epoch) return false
      versions.set(id, (versions.get(id) ?? 0) + 1)
      icons.value[id] = result.icon; errors.value[id] = false
      return true
    } catch (error) { if (session.value === epoch) throw error; return false }
    finally { if (session.value === epoch) saving.value[id] = false }
  }
  function reset(): void {
    ++session.value
    for (const controller of controllers) controller.abort()
    controllers.clear()
    clearTimeout(timer); timer = undefined
    pending.clear(); loading.clear(); versions.clear()
    icons.value = {}; errors.value = {}; saving.value = {}
  }
  function changeSession(event: Event): void {
    const current = sessionGeneration()
    // A refresh rotates the token within the same session, including pending icon commands.
    if ((event as CustomEvent<string | null>).detail !== null && current === authSession) return
    authSession = current
    reset()
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession)
  onScopeDispose(() => { reset(); window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession) })
  return { icons, errors, saving, session, ensure, save }
})
