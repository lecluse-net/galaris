import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { AUTH_TOKEN_CHANGED_EVENT, sessionGeneration } from '@/core/api'

/** Last non-null choice, shared between selectors for the current browser session. */
export const useAgentSelectionStore = defineStore('agent-selection', () => {
  const selectedAgentId = ref<number | null>(null)
  let generation = sessionGeneration()

  function synchronizeSession(event?: Event): void {
    const current = sessionGeneration()
    if (current !== generation || (event as CustomEvent | undefined)?.detail === null) {
      selectedAgentId.value = null
    }
    generation = current
  }

  function remember(agentId: number | null): void {
    synchronizeSession()
    if (agentId !== null) selectedAgentId.value = agentId
  }

  function defaultAgentId(agents: readonly { id: number }[]): number | null {
    synchronizeSession()
    return agents.some(agent => agent.id === selectedAgentId.value)
      ? selectedAgentId.value : agents[0]?.id ?? null
  }

  window.addEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronizeSession)
  onScopeDispose(() => window.removeEventListener(AUTH_TOKEN_CHANGED_EVENT, synchronizeSession))
  return { selectedAgentId, remember, defaultAgentId }
})
