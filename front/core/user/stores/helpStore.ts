import { defineStore } from 'pinia'
import { computed, ref, watch } from 'vue'
import { sessionGeneration } from '@/core/api'
import { useAuthStore } from './authStore'
import { helpService } from '../services/helpService'

export const useHelpStore = defineStore('context-help', () => {
  const auth = useAuthStore()
  const accountId = computed(() => auth.isAuthenticated ? auth.user?.id ?? null : null)
  const dismissed = ref<string[]>([])
  const pending = ref<string[]>([])
  const ready = ref(false)
  const loadError = ref(false)
  const saveErrors = ref<string[]>([])
  let epoch = 0
  let loading: Promise<void> | undefined

  watch(accountId, () => {
    epoch += 1
    dismissed.value = []
    pending.value = []
    saveErrors.value = []
    ready.value = false
    loadError.value = false
    loading = undefined
  }, { flush: 'sync' })

  async function load(): Promise<void> {
    if (!auth.isAuthenticated) return
    if (loading) return loading
    const operation = epoch
    const generation = sessionGeneration()
    const current = () => operation === epoch && generation === sessionGeneration()
    loading = (async () => {
      loadError.value = false
      try {
        const keys = await helpService.listDismissed()
        if (!current()) return
        // A late read must not undo a successful acknowledgement in this session.
        dismissed.value = [...new Set([...dismissed.value, ...keys])]
        ready.value = true
      } catch {
        if (current()) loadError.value = true
      } finally {
        if (current()) loading = undefined
      }
    })()
    return loading
  }

  async function dismiss(helpKey: string): Promise<void> {
    if (!auth.isAuthenticated || !ready.value || pending.value.includes(helpKey)) return
    const operation = epoch
    const generation = sessionGeneration()
    const current = () => operation === epoch && generation === sessionGeneration()
    pending.value.push(helpKey)
    saveErrors.value = saveErrors.value.filter(key => key !== helpKey)
    try {
      await helpService.dismiss(helpKey)
      if (current()) dismissed.value = [...new Set([...dismissed.value, helpKey])]
    } catch {
      if (current()) saveErrors.value.push(helpKey)
    } finally {
      if (current()) pending.value = pending.value.filter(key => key !== helpKey)
    }
  }

  return { accountId, dismissed, pending, ready, loadError, saveErrors, load, dismiss }
})
