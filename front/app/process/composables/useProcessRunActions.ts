import { onScopeDispose, ref, watch } from 'vue'
import { useInterval } from 'quasar'
import type { useProcessStore } from '../stores/processStore'
import type { ProcessRun } from '../services/processService'

interface RunActionOptions {
  store: ReturnType<typeof useProcessStore>
  canAdmin: () => boolean
  canOperate: () => boolean
  canAnalyze: () => boolean
  notify: (type: 'positive' | 'negative', message: string) => void
  errorDetail: (error: unknown) => string
  translate: (key: string) => string
  confirmRemoval: (proceed: () => Promise<void>) => void
}

/** Own the selected run's dialog, asynchronous actions and polling lifetime. */
export function useProcessRunActions(options: RunActionOptions) {
  const { store, notify, errorDetail, translate } = options
  const { registerInterval, removeInterval } = useInterval()
  const runDetailDialog = ref(false)
  const runDetailLoading = ref(false)
  let autoRefreshing = false
  let reloadPending = false
  let selection = 0
  const terminal = (status: string) => ['success', 'error', 'cancelled'].includes(status)

  async function openRun(row: Pick<ProcessRun, 'id'>): Promise<void> {
    selection += 1
    runDetailDialog.value = true
    runDetailLoading.value = true
    const request = store.detailRequest + 1
    try {
      await store.openRun(row.id)
    } catch (error) {
      if (store.detailRequest !== request) return
      runDetailDialog.value = false
      notify('negative', errorDetail(error))
    } finally {
      if (store.detailRequest === request) runDetailLoading.value = false
    }
  }

  async function removeRun(run: ProcessRun): Promise<void> {
    if (!options.canAdmin() || !terminal(run.status)) return
    options.confirmRemoval(async () => {
      if (!options.canAdmin()) return
      const request = store.detailRequest
      try {
        await store.deleteRun(run.id)
        const deletedSelection = store.detailRequest === request + 1 && store.currentRun === null
        if (store.detailRequest !== request && !deletedSelection) return
        if (deletedSelection) runDetailDialog.value = false
        notify('positive', translate('processes.runDeleted'))
      } catch (error) {
        if (store.detailRequest === request) notify('negative', errorDetail(error))
      }
    })
  }

  async function act(action: 'refreshRun' | 'cancelRun' | 'retryRun' | 'analyzeRun'): Promise<void> {
    if (!(action === 'analyzeRun' ? options.canAnalyze() : options.canOperate())) return
    const id = store.currentRun?.id
    if (!id) return
    const request = selection
    try {
      await store[action](id)
      if (action === 'retryRun' && request === selection && store.currentRun?.id === id) {
        notify('positive', translate('processes.retried'))
      }
    } catch (error) {
      if (request === selection) notify('negative', errorDetail(error))
    }
  }

  async function reloadCurrent(): Promise<void> {
    if (!runDetailDialog.value || !store.currentRun) return
    if (autoRefreshing) { reloadPending = true; return }
    autoRefreshing = true
    try { await store.reloadRun(store.currentRun.id) }
    catch (error) { console.error('Automatic process refresh failed:', error) }
    finally {
      autoRefreshing = false
      if (reloadPending) { reloadPending = false; void reloadCurrent() }
    }
  }

  watch(runDetailDialog, (open) => {
    if (!open) {
      selection += 1
      runDetailLoading.value = false
      store.closeRun()
      reloadPending = false
      removeInterval()
    }
  }, { flush: 'sync' })

  watch(() => store.currentRun?.status, (status) => {
    removeInterval()
    if (!status || terminal(status) || !runDetailDialog.value) return
    registerInterval(() => { void reloadCurrent() }, 5000)
  }, { immediate: true })

  onScopeDispose(() => {
    selection += 1
    reloadPending = false
    store.closeRun()
    removeInterval()
  })

  return {
    runDetailDialog, runDetailLoading, openRun, removeRun, reloadCurrent,
    refreshCurrent: () => act('refreshRun'),
    cancelCurrent: () => act('cancelRun'),
    retryCurrent: () => act('retryRun'),
    analyzeCurrent: () => act('analyzeRun'),
  }
}
