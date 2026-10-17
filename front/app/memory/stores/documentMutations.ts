import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'

/** Pending commands are shared by editors and library views, never persisted as data. */
export const useDocumentMutations = defineStore('memory.documentMutations', () => {
  const deleting = ref<Record<string, number>>({})
  let sequence = 0
  let session = sessionGeneration()

  function beginDeletion(id: string): (() => void) | null {
    if (deleting.value[id] !== undefined) return null
    const command = ++sequence
    deleting.value[id] = command
    return () => {
      if (deleting.value[id] === command) delete deleting.value[id]
    }
  }
  function changeSession(event: Event): void {
    const current = sessionGeneration()
    if ((event as CustomEvent<string | null>).detail !== null && current === session) return
    session = current
    deleting.value = {}
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession)
  onScopeDispose(() => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, changeSession))
  return { deleting, beginDeletion }
})
