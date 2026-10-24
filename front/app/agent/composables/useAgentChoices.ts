import { computed, onScopeDispose, reactive, ref } from 'vue'
import { isAxiosError } from 'axios'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'
import { getAgentSelection, type AgentSelectionOption } from '../services/agentSelectionService'

/** Scoped display metadata for domain selectors, independent of Agent administration. */
export function useAgentChoices() {
  const agents = ref<AgentSelectionOption[]>([])
  const loading = ref(false)
  let revision = 0
  let generation = sessionGeneration()
  const sortedAgents = computed(() => [...agents.value].sort((a, b) => a.label.localeCompare(b.label)))
  function synchronize(): void {
    const current = sessionGeneration()
    if (current === generation) return
    generation = current
    revision++
    agents.value = []
    loading.value = false
  }
  async function fetchAgents(): Promise<void> {
    synchronize()
    const request = ++revision
    const session = sessionGeneration()
    loading.value = true
    try {
      const options = await getAgentSelection('management')
      if (request === revision && session === sessionGeneration()) agents.value = options
    } catch (error) {
      if (request === revision && session === sessionGeneration() && isAxiosError(error)
        && [401, 403].includes(error.response?.status ?? 0)) agents.value = []
      throw error
    } finally {
      if (request === revision) loading.value = false
    }
  }
  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronize)
  onScopeDispose(() => {
    revision++
    window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronize)
  })
  return reactive({ agents, sortedAgents, loading, fetchAgents })
}
