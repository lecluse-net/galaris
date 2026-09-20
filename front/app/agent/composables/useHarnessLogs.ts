import { computed, onScopeDispose, ref, watch } from 'vue'
import { sessionGeneration } from '@/core/api'
import { startVisiblePolling } from '@/core/util'
import type { Agent } from '../services/agentService'

/** Own the log selection and its polling lifetime, including late responses. */
export function useHarnessLogs(
  load: (agentId: number) => Promise<string[]>,
  fallback: (agent: Agent, failed: boolean) => string,
) {
  const showHarnessLogsDialog = ref(false)
  const harnessLogsAgent = ref<Agent | null>(null)
  const harnessLogs = ref<string[]>([])
  const harnessLogsLoading = ref(false)
  let selection = 0
  let request = 0
  let stopPolling: (() => void) | undefined
  const harnessLogsAgentName = computed(() => harnessLogsAgent.value
    ? `${harnessLogsAgent.value.first_name} ${harnessLogsAgent.value.last_name} (${harnessLogsAgent.value.code})`
    : '')

  async function fetchHarnessLogs(): Promise<void> {
    const agent = harnessLogsAgent.value
    if (!agent || harnessLogsLoading.value) return
    const ownSelection = selection
    const ownRequest = ++request
    const generation = sessionGeneration()
    const current = () => selection === ownSelection && request === ownRequest && generation === sessionGeneration()
    harnessLogsLoading.value = true
    try {
      const lines = await load(agent.id)
      if (current()) harnessLogs.value = lines.length ? lines : [fallback(agent, false)]
    } catch {
      if (current()) harnessLogs.value = [fallback(agent, true)]
    } finally {
      if (current()) harnessLogsLoading.value = false
    }
  }

  function closeHarnessLogs(): void {
    selection += 1
    request += 1
    stopPolling?.()
    stopPolling = undefined
    harnessLogsAgent.value = null
    harnessLogs.value = []
    harnessLogsLoading.value = false
    showHarnessLogsDialog.value = false
  }

  async function openHarnessLogs(agent: Agent): Promise<void> {
    closeHarnessLogs()
    const ownSelection = selection
    harnessLogsAgent.value = agent
    showHarnessLogsDialog.value = true
    await fetchHarnessLogs()
    if (selection === ownSelection && showHarnessLogsDialog.value) {
      stopPolling = startVisiblePolling(fetchHarnessLogs, 2000)
    }
  }

  watch(showHarnessLogsDialog, opened => { if (!opened && harnessLogsAgent.value) closeHarnessLogs() }, { flush: 'sync' })
  onScopeDispose(closeHarnessLogs)
  return { showHarnessLogsDialog, harnessLogs, harnessLogsLoading, harnessLogsAgentName,
    fetchHarnessLogs, openHarnessLogs, closeHarnessLogs }
}
